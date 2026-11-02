import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import requests
from engine import street_geocoder as g


def feature(district='大雅區', name='中清路三段', coordinates=None):
    return {'properties': {'countrycode':'TW','city':'臺中市','district':district,
            'name':name,'osm_key':'highway','osm_id':123},
            'geometry':{'type':'Point','coordinates':coordinates or [120.647,24.221]}}


class StreetGeocoderTests(unittest.TestCase):
    def test_wrong_district_or_road_is_not_used(self):
        self.assertIsNone(g.select_road([feature(district='西屯區')], '大雅區', '中清路三段'))
        self.assertIsNone(g.select_road([feature(name='中清路二段')], '大雅區', '中清路三段'))

    def test_valid_road_and_invalid_coordinates(self):
        self.assertEqual(g.select_road([feature()], '大雅區', '中清路三段')['precision'], 'road_segment')
        self.assertIsNone(g.select_road([feature(coordinates=[0,0])], '大雅區', '中清路三段'))

    def test_cache_prevents_repeated_provider_calls(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(g,'CACHE_DIR',Path(tmp)), patch.object(g.requests,'get') as get:
            get.return_value = Mock(**{'json.return_value': {'features':[feature()]}})
            first=g.locate_road('大雅區','中清路三段')
            self.assertEqual(first, g.locate_road('大雅區','中清路三段'))
            get.assert_called_once()

    def test_timeout_does_not_fabricate_location(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(g,'CACHE_DIR',Path(tmp)), patch.object(g.requests,'get',side_effect=requests.Timeout):
            with self.assertRaises(g.StreetLookupError):
                g.locate_road('大雅區','中清路三段')

    def test_unknown_road_does_not_call_provider(self):
        with patch.object(g.requests,'get') as get:
            with self.assertRaises(ValueError):
                g.locate_road('大雅區','不存在的路')
            get.assert_not_called()
