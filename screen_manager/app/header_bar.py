"""Top bar of a screen: what the firmware draws right of the screen name.

Firmware 0.2.32+ only draws. This module decides everything that needs Home Assistant: an
entity's text (number format, units, translated states), its icon, its accent colour
and whether it shows at all. Clock, analog clock and date tick on the screen itself, and a
relative time ("5 min ago") travels as a unix time, so the screen counts the minutes
without any traffic.

Wire format, one message after the layout: {"v":1,"op":"header","items":[...]} with per item
"k" (clock, analog, date, text, ago), "i" (icon codepoint), "t" (text), "e" (unix time) and
"c" (accent colour RRGGBB).
"""
import math
import unicodedata
from datetime import datetime, time

import tile_icons
from core import HEADER_BUILTIN, HEADER_CONTENTS, HEADER_MAX_ITEMS, HEADER_MIN_FIRMWARE, HEADER_SHOWS, epoch, header_items, local_clock, short, state_word

# Characters the top bar's text font carries on both boards (`sublabel_big` in the profiles;
# tests/test_header_bar.py keeps them equal). Anything else folds to its base letter or goes.
GLYPHS = frozenset("<>—&@!,.?\"%()+-_:°0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyzäöüÄÖÜß/…·'#*=;²³µμéèëêïîóôàáâçñúû–")
TEXT_BYTES = 40
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
UNAVAILABLE = '—'

CONTENT_LABELS = {'state': 'Status', 'last_changed': 'Last changed'}
SHOW_LABELS = {'always': 'Always', 'active': 'Only when active'}

# Home Assistant's own words where they fit a small bar; the screen shows the rest as they come.
STATES = {
    'on': 'On', 'off': 'Off', 'home': 'Home', 'not_home': 'Away', 'open': 'Open', 'closed': 'Closed',
    'opening': 'Opening', 'closing': 'Closing', 'locked': 'Locked', 'unlocked': 'Unlocked', 'locking': 'Locking',
    'unlocking': 'Unlocking', 'jammed': 'Jammed', 'playing': 'Playing', 'paused': 'Paused', 'idle': 'Idle',
    'standby': 'Standby', 'buffering': 'Buffering', 'cleaning': 'Cleaning', 'docked': 'Docked', 'returning': 'Returning',
    'error': 'Error', 'heat': 'Heat', 'cool': 'Cool', 'heat_cool': 'Auto', 'auto': 'Auto', 'dry': 'Dry',
    'fan_only': 'Fan only', 'disarmed': 'Disarmed', 'armed_home': 'Armed home', 'armed_away': 'Armed away', 'armed_night': 'Armed night',
    'armed_vacation': 'Armed vacation', 'armed_custom_bypass': 'Armed', 'arming': 'Arming', 'pending': 'Pending',
    'triggered': 'Triggered', 'active': 'Active', 'above_horizon': 'Up', 'below_horizon': 'Down',
}
# device_class: (on, off). Tiles and cards show the same words from the screen's own copy, BINARY_WORDS in
# components/smart_display/tile_controls.h (firmware 0.2.53+); tests/test_binary_words.py keeps the two equal.
BINARY_STATES = {
    'battery': ('Low', 'Normal'), 'battery_charging': ('Charging', 'Not charging'), 'carbon_monoxide': ('Danger', 'Safe'),
    'cold': ('Cold', 'Normal'), 'connectivity': ('Connected', 'Disconnected'), 'door': ('Open', 'Closed'),
    'garage_door': ('Open', 'Closed'), 'gas': ('Danger', 'Safe'), 'heat': ('Hot', 'Normal'), 'light': ('Light', 'Dark'),
    'lock': ('Open', 'Locked'), 'moisture': ('Wet', 'Dry'), 'motion': ('Motion', 'No motion'),
    'moving': ('Moving', 'Still'), 'occupancy': ('Occupied', 'Clear'), 'opening': ('Open', 'Closed'), 'plug': ('Plugged in', 'Unplugged'),
    'power': ('On', 'Off'), 'presence': ('Home', 'Away'), 'problem': ('Problem', 'OK'), 'running': ('Active', 'Inactive'),
    'safety': ('Unsafe', 'Safe'), 'smoke': ('Smoke', 'No smoke'), 'sound': ('Sound', 'Silent'), 'tamper': ('Tampering', 'OK'),
    'update': ('Update', 'Up to date'), 'vibration': ('Vibration', 'Still'), 'window': ('Open', 'Closed'),
}
# Icon names from tile_icons; the fonts of both boards carry every one of them.
BINARY_ICONS = {  # device_class: (on, off)
    'motion': ('motion-sensor', 'motion-sensor'), 'occupancy': ('home-account', 'home-account'),
    'presence': ('home-account', 'home-account'), 'door': ('door-open', 'door-closed'), 'garage_door': ('garage', 'garage'),
    'opening': ('door-open', 'door-closed'), 'window': ('window-closed-variant', 'window-closed-variant'),
    'connectivity': ('router-wireless', 'router-wireless'), 'plug': ('power-plug', 'power-plug'), 'power': ('flash', 'flash'),
    'moisture': ('water-alert', 'water'), 'smoke': ('smoke-detector', 'smoke-detector'), 'gas': ('meter-gas', 'meter-gas'),
    'carbon_monoxide': ('smoke-detector', 'smoke-detector'), 'lock': ('lock-open-variant', 'lock'),
    'battery': ('battery-high', 'battery-high'), 'battery_charging': ('battery-high', 'battery-high'),
    'problem': ('alert-outline', 'check'), 'safety': ('alert-outline', 'check'), 'tamper': ('alert-outline', 'check'),
    'vibration': ('alert-outline', 'check'), 'heat': ('fire', 'fire'), 'cold': ('snowflake', 'snowflake'),
    'light': ('weather-sunny', 'weather-night'), 'running': ('play', 'stop'), 'sound': ('music-note', 'music-note'),
    'update': ('cog', 'cog'), 'moving': ('run', 'run'),
}
SENSOR_ICONS = {
    'temperature': 'thermometer', 'humidity': 'water-percent', 'moisture': 'water-percent', 'power': 'flash', 'energy': 'flash',
    'apparent_power': 'flash', 'reactive_power': 'flash', 'voltage': 'flash', 'current': 'flash', 'power_factor': 'flash',
    'battery': 'battery-high', 'illuminance': 'weather-sunny', 'pressure': 'gauge', 'atmospheric_pressure': 'gauge',
    'carbon_dioxide': 'molecule-co2', 'gas': 'meter-gas', 'water': 'water', 'signal_strength': 'router-wireless',
    'timestamp': 'clock-outline', 'duration': 'timer-outline', 'pm1': 'air-purifier', 'pm25': 'air-purifier',
    'pm10': 'air-purifier', 'aqi': 'air-purifier', 'volatile_organic_compounds': 'air-purifier', 'wind_speed': 'weather-windy',
    'speed': 'weather-windy', 'precipitation': 'weather-rainy', 'precipitation_intensity': 'weather-rainy',
    'irradiance': 'solar-power', 'date': 'calendar',
}
DOMAIN_ICONS = {
    'light': 'lightbulb', 'switch': 'toggle-switch', 'input_boolean': 'toggle-switch', 'fan': 'fan', 'cover': 'window-shutter',
    'climate': 'thermostat', 'vacuum': 'robot-vacuum', 'media_player': 'speaker', 'scene': 'palette', 'script': 'script-text',
    'button': 'gesture-tap-button', 'input_button': 'gesture-tap-button', 'person': 'account', 'device_tracker': 'map-marker',
    'zone': 'account-group', 'lock': 'lock', 'alarm_control_panel': 'shield-home', 'timer': 'timer-outline', 'counter': 'gauge',
    'event': 'bell-ring', 'input_datetime': 'calendar', 'input_text': 'script-text', 'water_heater': 'water-boiler',
    'humidifier': 'air-purifier', 'select': 'cog', 'input_select': 'cog', 'number': 'gauge', 'input_number': 'gauge',
    'sensor': 'gauge', 'binary_sensor': 'gauge',
}
# Their state is the moment they last ran or fired: the bar shows how long ago.
MOMENT_DOMAINS = frozenset(['scene', 'button', 'input_button', 'event'])
INACTIVE = frozenset(['off', 'closed', 'not_home', 'idle', 'docked', 'standby', 'locked', 'disarmed', 'paused', 'below_horizon'])
AMBER, GREEN, RED, BLUE, ORANGE, TEAL = 'FFB300', '43A047', 'E53935', '2196F3', 'FF6F22', '009688'
ALARM_CLASSES = frozenset(['problem', 'safety', 'smoke', 'gas', 'carbon_monoxide', 'moisture', 'tamper'])

def clean_text(text):
    """Text the screen can draw: known glyphs, accents folded to the base letter, at most TEXT_BYTES."""
    out = []
    for char in unicodedata.normalize('NFC', str(text)):
        if char in GLYPHS:
            out.append(char)
            continue
        base = unicodedata.normalize('NFKD', char)[0]
        if base in GLYPHS:
            out.append(base)
    return short(''.join(out).strip(), TEXT_BYTES)

def number_text(value, precision=None):
    """A number as Home Assistant writes it: decimal point, commas between thousands."""
    if precision is None:
        # Without a display precision HA keeps integers whole and shows at most three decimals.
        digits = 0 if float(value).is_integer() else 3
        text = f'{value:.{digits}f}'
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
    else:
        text = f'{value:.{precision}f}'
    negative = text.startswith('-')
    whole, _, fraction = text.lstrip('-').partition('.')
    grouped = f'{int(whole):,}'
    result = grouped + ('.' + fraction if fraction else '')
    # "-0" and "-0.0" are just zero.
    return '-' + result if negative and any(c not in '0.,' for c in result) else result

def with_unit(text, unit):
    """Home Assistant's spacing: "21.3 °C", "65%", "18°"."""
    if not unit:
        return text
    return text + unit if unit in ('%', '°') else f'{text} {unit}'

def precision_of(entry):
    options = ((entry or {}).get('options') or {}).get('sensor') or {}
    for key in ('display_precision', 'suggested_display_precision'):
        value = options.get(key)
        if type(value) is int and 0 <= value <= 6:
            return value
    return None

def numeric(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None

def short_date(moment):
    return f'{moment.day} {MONTHS[moment.month - 1]}'

def value(entity, state, entry=None, units=None, tz=None, words=None):
    """(text, unix time) an entity shows as its state; exactly one of them is set. `words` are Home Assistant's
    translations: its word shows where the bar has none of its own ("Rinsing" for rinsing, app 0.2.67)."""
    domain = entity.split('.')[0]
    raw = state.get('state') if state else None
    attrs = (state or {}).get('attributes') or {}
    if raw in (None, '', 'unavailable', 'unknown'):
        return UNAVAILABLE, None
    if domain in MOMENT_DOMAINS:
        return (None, epoch(raw)) if epoch(raw) else (UNAVAILABLE, None)
    if domain == 'script':
        moment = epoch(attrs.get('last_triggered'))
        return ('Running', None) if raw == 'on' else (None, moment) if moment else ('Never run', None)
    if domain == 'sun':
        # The next event: sunset while the sun is up, sunrise while it is down.
        clock = local_clock(attrs.get('next_setting' if raw == 'above_horizon' else 'next_rising'), tz)
        return (clock or STATES.get(raw, raw)), None
    if domain == 'weather':
        temperature = numeric(attrs.get('temperature'))
        if temperature is None:
            return UNAVAILABLE, None
        return with_unit(number_text(temperature, 0), attrs.get('temperature_unit') or (units or {}).get('temperature', '°C')), None
    if domain == 'climate':
        current = numeric(attrs.get('current_temperature'))
        if current is not None:
            return with_unit(number_text(current, 1), (units or {}).get('temperature', '°C')), None
    if domain in ('person', 'device_tracker'):
        return STATES.get(raw, raw), None
    if domain == 'binary_sensor':
        pair = BINARY_STATES.get(attrs.get('device_class'), ('On', 'Off'))
        return (pair[0] if raw == 'on' else pair[1] if raw == 'off' else raw), None
    if domain == 'input_datetime':
        # "2026-09-15 07:30:00", "2026-09-15" or just "07:30:00".
        try:
            moment = datetime.fromisoformat(raw) if attrs.get('has_date') else datetime.combine(datetime.min, time.fromisoformat(raw))
        except ValueError:
            return raw, None
        if attrs.get('has_date') and attrs.get('has_time'):
            return f'{short_date(moment)} {moment:%H:%M}', None
        return (short_date(moment) if attrs.get('has_date') else f'{moment:%H:%M}'), None
    if domain == 'sensor' and attrs.get('device_class') == 'timestamp':
        return (None, epoch(raw)) if epoch(raw) else (raw, None)
    if domain == 'sensor' and attrs.get('device_class') == 'date':
        try:
            return short_date(datetime.fromisoformat(raw)), None
        except ValueError:
            return raw, None
    number = numeric(raw)
    if number is not None and domain in ('sensor', 'number', 'input_number', 'counter', 'zone'):
        return with_unit(number_text(number, precision_of(entry)), attrs.get('unit_of_measurement')), None
    if domain in ('input_text', 'input_select', 'select'):
        return state_word(entity, raw, attrs, entry, words) or raw, None
    if raw in STATES:
        return STATES[raw], None
    return state_word(entity, raw, attrs, entry, words) or raw[:1].upper() + raw[1:], None

def active(entity, state):
    """"Only when active": on, open, home, detected, playing, heating, or a number other than zero."""
    raw = state.get('state') if state else None
    domain = entity.split('.')[0]
    if raw in (None, '', 'unavailable', 'unknown'):
        return False
    if domain in ('person', 'device_tracker'):
        return raw == 'home'
    if domain in MOMENT_DOMAINS or domain in ('weather', 'sun') and raw != 'below_horizon':
        return True
    number = numeric(raw)
    if number is not None:
        return number != 0
    return raw not in INACTIVE

def accent(entity, state):
    """Icon colour while an entity is active, like Home Assistant's badges; None keeps the calm grey."""
    raw = state.get('state') if state else None
    domain = entity.split('.')[0]
    attrs = (state or {}).get('attributes') or {}
    if domain == 'binary_sensor' and raw == 'on':
        return RED if attrs.get('device_class') in ALARM_CLASSES else AMBER
    if domain in ('light', 'switch', 'input_boolean', 'fan') and raw == 'on':
        return AMBER
    if domain in ('person', 'device_tracker') and raw == 'home':
        return GREEN
    if domain == 'climate' and raw in ('heat', 'cool'):
        return ORANGE if raw == 'heat' else BLUE
    # Home Assistant's own state colours: armed and locked green, on their way orange, alarm and open red.
    if domain == 'alarm_control_panel':
        return RED if raw == 'triggered' else ORANGE if raw in ('arming', 'pending') else GREEN if raw and raw.startswith('armed') else None
    if domain == 'lock':
        return GREEN if raw == 'locked' else ORANGE if raw in ('locking', 'unlocking', 'opening') else RED if raw in ('unlocked', 'open', 'jammed') else None
    if domain == 'media_player' and raw == 'playing':
        return BLUE
    if domain == 'vacuum' and raw == 'cleaning':
        return TEAL
    return None

def auto_icon(entity, state, entry=None):
    """Codepoint of the icon Home Assistant would show: its own mdi icon, else Home Assistant's default icon for this state
    (app 0.2.67, the same as a tile), else the device class and domain tables."""
    attrs = (state or {}).get('attributes') or {}
    raw = (state or {}).get('state')
    own = tile_icons.ha_icon(attrs) or tile_icons.default_glyph(entity, raw, attrs, entry)
    if own:
        return own
    domain, device_class = entity.split('.')[0], attrs.get('device_class')
    if domain == 'weather':
        name = tile_icons.WEATHER.get(raw, 'weather-partly-cloudy')
    elif domain == 'light' and raw == 'off':
        name = 'lightbulb-off'
    elif domain == 'sun':
        name = 'weather-sunset-down' if raw == 'above_horizon' else 'weather-sunset-up'
    elif domain == 'binary_sensor' and device_class in BINARY_ICONS:
        name = BINARY_ICONS[device_class][0 if raw == 'on' else 1]
    elif domain == 'sensor' and device_class in SENSOR_ICONS:
        name = SENSOR_ICONS[device_class]
    elif domain == 'lock' and raw in ('unlocked', 'open', 'unlocking'):
        name = 'lock-open-variant'
    else:
        name = DOMAIN_ICONS.get(domain, tile_icons.FALLBACK)
    return tile_icons.GLYPHS[name]

def entity_item(item, states, registry=None, units=None, tz=None, words=None):
    """(wire item, shown) for one entity item; the wire item exists even while hidden, for the editor."""
    entity = item['entity']
    state = states.get(entity)
    wire = {'k': 'text'}
    if item['icon'] == 'auto':
        wire['i'] = auto_icon(entity, state, (registry or {}).get(entity) if isinstance(registry, dict) else None)
    elif item['icon'] != 'none':
        wire['i'] = tile_icons.ICONS[item['icon']][0]
    if item['content'] == 'last_changed':
        moment = epoch((state or {}).get('last_changed'))
        text, moment = (None, moment) if moment else (UNAVAILABLE, None)
    else:
        text, moment = value(entity, state, (registry or {}).get(entity), units, tz, words)
    if moment:
        wire.update(k='ago', e=moment)
    else:
        wire['t'] = clean_text(text) or UNAVAILABLE
    color = accent(entity, state)
    if color:
        wire['c'] = color
    return wire, item['show'] == 'always' or active(entity, state)

def message(layout, states, registry=None, units=None, tz=None, words=None):
    items = []
    for item in header_items(layout):
        if item['type'] in HEADER_BUILTIN:
            items.append({'k': item['type']})
            continue
        wire, shown = entity_item(item, states, registry, units, tz, words)
        if shown:
            items.append(wire)
    return {'v': 1, 'op': 'header', 'items': items}

def preview(header, states, registry=None, units=None, tz=None, words=None):
    """What the editor's mockup shows per item, hidden ones included and marked."""
    result = []
    for item in header['items']:
        if item['type'] in HEADER_BUILTIN:
            result.append({'k': item['type'], 'name': HEADER_BUILTIN[item['type']], 'shown': True})
            continue
        wire, shown = entity_item(item, states, registry, units, tz, words)
        attrs = (states.get(item['entity']) or {}).get('attributes') or {}
        result.append({**wire, 'name': attrs.get('friendly_name') or item['entity'], 'shown': shown,
                       'auto_icon': auto_icon(item['entity'], states.get(item['entity']))})
    return result

def suggestions(screen, entities, states, registry=None, limit=8):
    """A handful of useful items for this screen: its own room's climate and power first, then the house.

    The room is the screen's area, or an area named like the screen. Diagnostic entities (a plug's own
    temperature) never qualify."""
    rooms = {name.casefold() for name in (screen.get('area'), screen.get('name'), (screen.get('layout') or {}).get('title')) if name}
    def attrs(entity):
        return (states.get(entity['id']) or {}).get('attributes') or {}
    def usable(entity):
        return ((states.get(entity['id']) or {}).get('state') not in (None, 'unavailable', 'unknown')
                and not ((registry or {}).get(entity['id']) or {}).get('entity_category'))
    def pick(label, test, content='state'):
        found = sorted((e for e in entities if test(e) and usable(e)), key=lambda e: (e['area'].casefold() not in rooms, e['name'].casefold()))
        if found:
            entity = found[0]
            picks.append({'label': label, 'name': entity['name'], 'area': entity['area'], 'icon': auto_icon(entity['id'], states.get(entity['id'])),
                          'item': {'type': 'entity', 'entity': entity['id'], 'content': content, 'icon': 'auto', 'show': 'always'}})
    def sensor(device_class):
        return lambda e: e['id'].startswith('sensor.') and attrs(e).get('device_class') == device_class and numeric(states[e['id']]['state']) is not None
    picks = []
    pick('Temperature', sensor('temperature'))
    pick('Humidity', sensor('humidity'))
    pick('Power usage', sensor('power'))
    pick('Last motion', lambda e: e['id'].startswith('binary_sensor.') and attrs(e).get('device_class') in ('motion', 'occupancy', 'presence'), 'last_changed')
    pick('Weather', lambda e: e['id'].startswith('weather.'))
    pick('People home', lambda e: e['id'] == 'zone.home')
    pick('Sunrise and sunset', lambda e: e['id'] == 'sun.sun')
    pick('CO₂', sensor('carbon_dioxide'))
    return picks[:limit]

def catalogue():
    """Choices the editor offers; labels in the order the sheet shows them."""
    return {'builtin': [{'type': key, 'label': label} for key, label in HEADER_BUILTIN.items()],
            'contents': [{'key': key, 'label': CONTENT_LABELS[key]} for key in HEADER_CONTENTS],
            'shows': [{'key': key, 'label': SHOW_LABELS[key]} for key in HEADER_SHOWS],
            'max_items': HEADER_MAX_ITEMS, 'min_firmware': '.'.join(map(str, HEADER_MIN_FIRMWARE))}
