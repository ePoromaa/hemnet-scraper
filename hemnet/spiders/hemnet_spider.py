# -*- coding: utf-8 -*-

from urlparse import urlparse
import re
import scrapy
from hemnet.items import HemnetItem
from scrapy import Selector

from sqlalchemy.orm import sessionmaker

from hemnet.models import HemnetItem as HemnetSQL, db_connect, create_hemnet_table

# BASE_URL = 'http://www.hemnet.se/salda/bostader?location_ids%5B%5D=17920'

BASE_URL = 'http://www.hemnet.se/salda/bostader?'


def start_urls(start, stop):
    return ['{}&page={}'.format(BASE_URL, x) for x in xrange(start, stop)]


class HemnetSpider(scrapy.Spider):
    name = 'hemnetspider'
    rotate_user_agent = True

    def __init__(self, start=1, stop=10, *args, **kwargs):
        super(HemnetSpider, self).__init__(*args, **kwargs)
        self.start = int(start)
        self.stop = int(stop)
        engine = db_connect()
        create_hemnet_table(engine)
        self.session = sessionmaker(bind=engine)()

    def start_requests(self):
        for url in start_urls(self.start, self.stop):
            yield scrapy.Request(url, self.parse)

    def parse(self, response):
        urls = response.css('#search-results li > div > a::attr("href")')
        for url in urls.extract():
            session = self.session
            q = session.query(HemnetSQL).filter(HemnetSQL.hemnet_id == get_hemnet_id(url))
            if not session.query(q.exists()).scalar():
                yield scrapy.Request(url, self.parse_detail_page)

    def parse_detail_page(self, response):
        item = HemnetItem()

        broker = response.css('.broker-info > p')[0]  # type: Selector
        property_attributes = get_property_attributes(response)

        item['url'] = response.url

        slug = urlparse(response.url).path.split('/')[-1]

        item['hemnet_id'] = get_hemnet_id(response.url)

        item['type'] = slug.split('-')[0]

        raw_rooms = property_attributes.get(u'Antal rum', '').replace(u' rum', u'').replace(u',', u'.')
        try:
            item['rooms'] = float(raw_rooms)
        except ValueError:
            pass

        try:
            fee = int(property_attributes.get(u'Avgift/månad', '').replace(u' kr/m\xe5n', '').replace(u'\xa0', u''))
        except ValueError:
            fee = None
        item['monthly_fee'] = fee

        try:
            item['square_meters'] = float(property_attributes.get(u'Boarea', '').split(' ')[0].replace(',', '.'))
        except ValueError:
            pass
        try:
            cost = int(property_attributes.get(u'Avgift/månad', '').replace(u' kr/m\xe5n', '').replace(u'\xa0', u''))
        except ValueError:
            cost = None
        item['cost_per_year'] = cost
        item['year'] = property_attributes.get(u'Byggår', '')  # can be '2008-2009'

        item['broker_name'] = broker.css('strong::text').extract_first()
        item['broker_phone'] = strip_phone(broker.css('.phone-number::attr("href")').extract_first())

        try:
            email = broker.xpath("a[contains(@href, 'mailto:')]/@href").extract_first().replace(u'mailto:', u'')
            item['broker_email'] = email
        except AttributeError:
            pass

        broker_firm = response.css('.broker-info > p')[1]  # type: Selector
        item['broker_firm'] = broker_firm.css('strong::text').extract_first()
        try:
            firm_phone = broker_firm.xpath("a[contains(@href, 'tel:')]/@href").extract_first()
            item['broker_firm_phone'] = firm_phone.replace(u'tel:', u'')
        except AttributeError:
            pass

        raw_price = response.css('.sold-property-price > span::text').extract_first()
        item['price'] = price_to_int(raw_price)

        get_selling_statistics(response, item)

        detail = response.css('.sold-property-details')[0]

        item['sold_date'] = detail.css('.metadata > time::attr("datetime")').extract_first()
        item['address'] = detail.css('h1::text').extract_first()

        item['geographic_area'] = detail.css('.area::text').extract_first().strip().lstrip(u',').strip().rstrip(u',')

        yield item


def get_hemnet_id(url):
    slug = urlparse(url).path.split('/')[-1]
    return int(slug.split('-')[-1])


def get_selling_statistics(response, item):
    for li in response.css('ul.selling-statistics > li'):
        key = li.css('::text').extract_first().strip()
        value = li.css('strong::text').extract_first()
        if value:
            if key == u'Begärt pris':
                item['asked_price'] = price_to_int(value)
            if key == u'Prisutveckling':
                item['price_trend_flat'], item['price_trend_percentage'] = price_trend(value)
            if key == u'Pris per kvadratmeter':
                item['price_per_square_meter'] = int(value.replace(u'\xa0', '').split(' ')[0])


def get_property_attributes(response):
    a = response.css('ul.property-attributes > li::text').extract()
    x = [x.strip() for x in a]
    b = response.css('ul.property-attributes > li > strong::text').extract()

    return dict(zip(x, b))


def price_to_int(price_text):
    return int(price_text.replace(u'\xa0', u'').replace(u' kr', u'').encode())


def strip_phone(phone_text):
    if phone_text:
        return phone_text.replace(u'tel:', u'')
    else:
        return u''


def price_trend(price_text):
    r = '(?P<sign>[+-])(?P<flat>\d*)\([+-]?(?P<percentage>\d*)\%\)$'

    temp = price_text.replace(u'\xa0', '').replace(' ', '').replace('kr', '')

    matches = re.search(r, temp)

    sign = matches.group('sign')
    flat = int('{}{}'.format(sign, matches.group('flat')))
    percentage = int('{}{}'.format(sign, matches.group('percentage')))
    return flat, percentage

