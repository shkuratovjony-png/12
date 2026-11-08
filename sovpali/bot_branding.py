"""Sync the public BotFather-equivalent profile fields on application startup.

Telegram Bot API: setMyName, setMyDescription (the pre-Start screen), and
setMyShortDescription (About / shared link). All requests use the existing
BOT_TOKEN; no BotFather manual access or new credentials are necessary.
"""
BOT_NAME = "Совпали"

BOT_DESCRIPTION = """💞 «Совпали» — здесь знакомства не случайны.

Подбираем идеальную пару по астрологии, нумерологии и жизненной совместимости — для настоящих долгосрочных отношений.

Нажми «Старт» и узнай, кто тебе подходит."""

BOT_SHORT_DESCRIPTION = "«Совпали» — подбор идеальной пары по астрологии, нумерологии и ценностям. Здесь знакомство не случайно."

assert len(BOT_NAME) <= 64
assert len(BOT_DESCRIPTION) <= 512
assert len(BOT_SHORT_DESCRIPTION) <= 120


async def sync_bot_profile(bot):
    """Synchronize default+ru profile; failures must never stop the core bot."""
    try:
        old = await bot.get_my_description()
        old_short = await bot.get_my_short_description()
        print("[bot-profile] previous_description=" + repr(old.description), flush=True)
        print("[bot-profile] previous_about=" + repr(old_short.short_description), flush=True)
    except Exception as exc:
        print("[bot-profile] old profile read failed: " + type(exc).__name__, flush=True)

    operations = [
        ("name-default", bot.set_my_name(name=BOT_NAME)),
        ("name-ru", bot.set_my_name(name=BOT_NAME, language_code="ru")),
        ("description-default", bot.set_my_description(description=BOT_DESCRIPTION)),
        ("description-ru", bot.set_my_description(description=BOT_DESCRIPTION, language_code="ru")),
        ("about-default", bot.set_my_short_description(short_description=BOT_SHORT_DESCRIPTION)),
        ("about-ru", bot.set_my_short_description(short_description=BOT_SHORT_DESCRIPTION, language_code="ru")),
    ]
    for label, coro in operations:
        try:
            ok = await coro
            print("[bot-profile] " + label + " " + ("OK" if ok else "not-confirmed"), flush=True)
        except Exception as exc:
            print("[bot-profile] " + label + " failed: " + type(exc).__name__ + " " + str(exc)[:100], flush=True)
    try:
        for code in ("", "ru"):
            name = await bot.get_my_name(language_code=code)
            desc = await bot.get_my_description(language_code=code)
            about = await bot.get_my_short_description(language_code=code)
            verified = (name.name == BOT_NAME
                        and desc.description == BOT_DESCRIPTION
                        and about.short_description == BOT_SHORT_DESCRIPTION)
            print("[bot-profile] verify " + (code or "default") + " " +
                  ("OK" if verified else "MISMATCH"), flush=True)
    except Exception as exc:
        print("[bot-profile] verification failed: " + type(exc).__name__, flush=True)
