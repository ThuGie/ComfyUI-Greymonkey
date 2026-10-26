"""Versioned creator settings, shared with hosted discovery and PHP planning."""
import json
from pathlib import Path
from . import client


def validate_catalog(data):
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('version'), str):
        raise client.GreymonkeyError('Unsupported creator catalog. Refresh or reinstall.')
    keys = {'category', 'presentation', 'expression_direction', 'body_direction', 'wardrobe_direction', 'item_policy'}
    if not isinstance(data.get('choices'), dict) or set(data['choices']) != keys or not isinstance(data.get('defaults'), dict) or set(data['defaults']) != keys:
        raise client.GreymonkeyError('Incomplete creator controls.')
    for key, values in data['choices'].items():
        if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v for v in values) or len(set(values)) != len(values) or data['defaults'][key] not in values:
            raise client.GreymonkeyError('Invalid creator choices: ' + key)
    categories = data.get('categories')
    if not isinstance(categories, dict) or set(categories) != set(data['choices']['category']) - {'automatic'}:
        raise client.GreymonkeyError('Incomplete creator category catalog.')
    seen = set()
    for category in categories.values():
        if not isinstance(category, dict) or not isinstance(category.get('scenarios'), list) or len(category['scenarios']) < 12:
            raise client.GreymonkeyError('Incomplete creator scenario catalog.')
        for scenario in category['scenarios']:
            if not isinstance(scenario, dict) or not all(isinstance(scenario.get(k), str) and scenario[k] for k in ('id', 'name', 'location_id', 'pose_id')) or scenario['id'] in seen:
                raise client.GreymonkeyError('Invalid or duplicated creator scenario.')
            seen.add(scenario['id'])
    return data


def catalog():
    data = client.catalog().get('creator_catalog')
    if data is None:
        data = json.loads((Path(__file__).parent / 'creator-profiles.json').read_text(encoding='utf-8'))
    return validate_catalog(data)


def settings(value):
    data = catalog()
    if not isinstance(value, dict) or set(value) - set(data['choices']):
        raise client.GreymonkeyError('Malformed Influencer Settings.')
    result = dict(data['defaults'], **value)
    for key, selected in result.items():
        if selected not in data['choices'][key]:
            raise client.GreymonkeyError(f'Unknown creator {key}: {selected}. Your saved choice has not been reset.')
    return result


class GreymonkeyInfluencerSettingsV2:
    CATEGORY = 'Greymonkey/Advanced'
    FUNCTION = 'build'
    RETURN_TYPES = ('GREYMONKEY_CREATOR',)
    RETURN_NAMES = ('creator_settings',)

    @classmethod
    def INPUT_TYPES(cls):
        data = catalog()
        return {'required': {key: (values, {'default': data['defaults'][key]}) for key, values in data['choices'].items()}}

    def build(self, **values):
        return ({'schema_version': 1, 'kind': 'creator', 'settings': settings(values)},)
