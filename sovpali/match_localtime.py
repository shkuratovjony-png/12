"""Offline local-time inference for matchmaking notifications.

Telegram Bot API does not expose the user's time zone. This is a best-effort
mapping from the profile's declared city (with a user-adjustable override).
Unrecognised cities default to Moscow time; do not describe them as verified.
Supports IANA zones, so places observing DST are handled properly.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re

_CITY_GROUPS = {
    "Europe/Kaliningrad": "калининград балтийск светлогорск зеленоградск гусев советск черняховск",
    "Europe/Moscow": "москва московская область санкт-петербург питер спб великий новгород тверь псков смоленск брянск калуга тула рязань владимир ярославль кострома иваново орел курск белгород воронеж липецк тамбов пенза сарaнск саранск нижний новгород нижегородская область чебоксары йошкар-ола казань набережные челны зеленодольск уфа ижевск пермь киров сыктывкар вологда архангельск мурманск петрозаводск ростов-на-дону ростов краснодар сочи анапа новороссийск армавир майкоп ставрополь пятигорск кисловодск ессентуки минеральные воды нальчик владикавказ грозный махачкала дербент астрахань волгоград саратов элиста севастополь симферополь керчь ялта",
    "Europe/Samara": "самара тольятти сызрань новокуйбышевск ульяновск димитровград оренбург орск саракташ бугуруслан",
    "Asia/Yekaterinburg": "екатеринбург екатеринбурк екатиринбург екатеренбург екатеринбур екат ебург екб верхняя пышма первоуральск ревда березовский среднеуральск нижний тагил каменск-уральский асбест серов краснотурьинск челябинск магнитогорск златоуст миасс копейск курган тюмень тобольск ишим ханты-мансийск сургут нижневартовск нефтеюганск ноябрьск новый уренгой салехард надым",
    "Asia/Omsk": "омск тара исилькуль калачинск",
    "Asia/Novosibirsk": "новосибирск бердск искитим обь краснообск барнаул бийск рубцовск белокуриха томск северск стрежевой",
    "Asia/Krasnoyarsk": "красноярск ачинск канск железногорск норильск назарово минусинск лесосибирск зеленогорск абакан черногорск кызыл дудинка",
    "Asia/Irkutsk": "иркутск ангарск шелехов братск усть-илимск черемхово усолье-сибирское улан-удэ северобайкальск",
    "Asia/Yakutsk": "якутск нерюнгри мирный алдан ленск благовещенск белогорск свободный тында чигирин",
    "Asia/Vladivostok": "владивосток артем артём надеждинск вольно-надеждинское тавричанка уссурийск находка арсеньев спасск-дальний партизанск лесозаводск большой камень фокино хабаровск комсомольск-на-амуре биробиджан лучегорск",
    "Asia/Sakhalin": "южно-сахалинск корсаков анива холмск невельск поронайск долинск охa оха ноглики",
    "Asia/Magadan": "магадан сусуман сокол",
    "Asia/Kamchatka": "петропавловск-камчатский елизово вилючинск анадырь певек",
    "Europe/Minsk": "минск борисов молодечно брест гомель витебск гродно могилев",
    "Europe/Kyiv": "киев київ харьков харків одесса одеса днепр дніпро львов львів запорожье запоріжжя",
    "Europe/Vilnius": "вильнюс вільнюс каунас клайпеда шяуляй паневежис",
    "Asia/Almaty": "алматы алмата алма-ата талдыкорган кызылорда шымкент туркестан тараз",
    "Asia/Aqtobe": "актобе уральск актау атырау",
    "Asia/Almaty": "алматы алма-ата астана нур-султан нур-султанн шымкент кызылорда актау атырау уральск актобе караганда кокшетау павлодар петропавловск костанай семипалатинск",
    "Asia/Bishkek": "бишкек ош джалал-абад каракол",
    "Asia/Tashkent": "ташкент самарканд бухара андижан фергана наманган",
    "Asia/Tbilisi": "тбилиси батуми кутаиси рустави",
    "Asia/Yerevan": "ереван гюмри ванадзор",
    "Asia/Baku": "баку сумгаит гянджа",
    "Europe/Istanbul": "стамбул анкара анталия измир",
    "Europe/Berlin": "берлин мюнхен гамбург",
    "Europe/Paris": "париж марсель лион",
    "Europe/London": "лондон манчестер",
    "America/New_York": "нью-йорк нью йорк бостон вашингтон",
    "America/Los_Angeles": "лос-анджелес сан-франциско сиэтл",
    "Asia/Dubai": "дубай абу-даби",
    "Asia/Shanghai": "пекин шанхай гуанчжоу шэньчжэнь",
}
# The map is explicit so ambiguous abbreviations do not override a full city.
_ALIASES = {
 "екатеринбург":"Asia/Yekaterinburg","екб":"Asia/Yekaterinburg",
 "владик":"Asia/Vladivostok","спб":"Europe/Moscow",
 "питер":"Europe/Moscow","мск":"Europe/Moscow",
 "нск":"Asia/Novosibirsk","нн":"Europe/Moscow",
 "москва":"Europe/Moscow","сахалин":"Asia/Sakhalin",
 "приморский край":"Asia/Vladivostok",
 "хабаровский край":"Asia/Vladivostok",
 "свердловская область":"Asia/Yekaterinburg",
 "челябинская область":"Asia/Yekaterinburg",
 "краснодарский край":"Europe/Moscow",
 "кемерово":"Asia/Novokuznetsk",
 "новокузнецк":"Asia/Novokuznetsk",
 "прокопьевск":"Asia/Novokuznetsk",
 "междуреченск":"Asia/Novokuznetsk",
 "южно-сахалинск":"Asia/Sakhalin",
 "сахалинская область":"Asia/Sakhalin",
}
_ZONES = dict(_ALIASES)
for zone, cities in _CITY_GROUPS.items():
    for city in cities.split():
        # Groups are for single-token names; multi-word aliases are explicit below.
        if city not in _ZONES:
            _ZONES[city] = zone
_ZONES.update({
 "нижний новгород":"Europe/Moscow",
 "ростов-на-дону":"Europe/Moscow",
 "набережные челны":"Europe/Moscow",
 "минеральные воды":"Europe/Moscow",
 "верхняя пышма":"Asia/Yekaterinburg",
 "нижний тагил":"Asia/Yekaterinburg",
 "новый уренгой":"Asia/Yekaterinburg",
 "ханты-мансийск":"Asia/Yekaterinburg",
 "нижневартовск":"Asia/Yekaterinburg",
 "комсомольск-на-амуре":"Asia/Vladivostok",
 "вольно-надеждинское":"Asia/Vladivostok",
 "большой камень":"Asia/Vladivostok",
 "южно-сахалинск":"Asia/Sakhalin",
 "петропавловск-камчатский":"Asia/Kamchatka",
 "нур-султан":"Asia/Almaty",
 "нью-йорк":"America/New_York",
 "лос-анджелес":"America/Los_Angeles",
 "сан-франциско":"America/Los_Angeles",
 "абу-даби":"Asia/Dubai",
})
# Russian cities can share names across distant regions. These are heuristics.
# Users may always override with /timezone.
def normalize_city(city):
    name=str(city or "").lower().strip().replace("ё","е")
    name=re.sub(r"^(?:г\.?|город|пос\.?|пгт)\s+","",name)
    return re.sub(r"\s+"," ",name).strip(" .,-")

def infer_zone(city):
    name=normalize_city(city)
    if name in _ZONES:return _ZONES[name],True
    for known,zone in _ZONES.items():
        if len(known)>=6 and (name.startswith(known+",") or name.startswith(known+" ") or name.endswith(" "+known)):
            return zone,True
    return "Europe/Moscow",False

def local_now(city, override=None, now_utc=None):
    zone=override or infer_zone(city)[0]
    instant=now_utc or datetime.now(timezone.utc)
    if instant.tzinfo is None:instant=instant.replace(tzinfo=timezone.utc)
    try:
        local=instant.astimezone(ZoneInfo(zone))
    except (ZoneInfoNotFoundError,ValueError,KeyError):
        zone="Europe/Moscow"
        local=instant.astimezone(ZoneInfo(zone))
    return local,zone
