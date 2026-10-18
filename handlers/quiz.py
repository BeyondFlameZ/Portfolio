"""Квиз-калькулятор: 4 вопроса → ориентир цены → телефон → заявка менеджеру."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

import db
import logic
from i18n import D, tr
from handlers.common import bad_phone_text, fmt_phone, menu_btn, kb, notify_owner, parse_phone, phone_kb

router = Router()
def QS():
    return D().QUIZ["questions"]


class Quiz(StatesGroup):
    answering = State()
    phone = State()


def q_view(i: int):
    q = QS()[i]
    rows = [[(o[1], f"qa:{i}:{o[0]}")] for o in q["options"]]
    rows.append([(tr("⬅️ Назад", "⬅️ Back"), f"qb:{i}")] if i else [menu_btn()])
    return (f"<b>{D().QUIZ['title']}</b> · {tr('вопрос', 'question')} {i + 1} {tr('из', 'of')} {len(QS())}\n\n{q['text']}", kb(rows))


@router.callback_query(F.data == "m:quiz")
async def quiz_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(Quiz.answering)
    await state.update_data(answers={})
    text, markup = q_view(0)
    await c.message.edit_text(f"{D().QUIZ['company']}\n" + tr(f"Ответьте на {len(QS())} вопроса — покажу примерную стоимость.",
                                                                f"Answer {len(QS())} questions and I'll show an estimated price.") + "\n\n" + text,
                              reply_markup=markup)
    await c.answer()


@router.callback_query(F.data.startswith("qb:"), Quiz.answering)
async def quiz_back(c: CallbackQuery):
    i = int(c.data[3:])
    text, markup = q_view(max(0, i - 1))
    await c.message.edit_text(text, reply_markup=markup)
    await c.answer()


@router.callback_query(F.data.startswith("qa:"), Quiz.answering)
async def quiz_answer(c: CallbackQuery, state: FSMContext):
    _, i, oid = c.data.split(":")
    i = int(i)
    st = await state.get_data()
    answers = dict(st.get("answers", {}))
    answers[QS()[i]["id"]] = oid
    await state.update_data(answers=answers)
    if i + 1 < len(QS()):
        text, markup = q_view(i + 1)
        await c.message.edit_text(text, reply_markup=markup)
        return await c.answer()
    est = logic.quiz_estimate(answers)
    est_s = f"{logic.money(est[0])} – {logic.money(est[1])}" if est else tr("рассчитает менеджер", "a manager will calculate")
    await state.update_data(estimate=est_s)
    await state.set_state(Quiz.phone)
    summary = "\n".join(f"• {q['text']} {logic.quiz_option_label(q['id'], answers.get(q['id'], ''))}" for q in QS())
    await c.message.edit_text(f"{summary}\n\n💰 {tr('Ориентир', 'Estimate')}: <b>{est_s}</b>\n\n"
                              + tr("Точную смету бесплатно посчитает прораб после замера.", "A foreman will prepare an exact quote for free after a site visit."))
    await c.message.answer(tr("Оставьте телефон — перезвоним в течение 15 минут:", "Leave your phone and we'll call you back within 15 minutes:"),
                           reply_markup=phone_kb())
    await c.answer()


@router.message(Quiz.phone)
async def quiz_phone(m: Message, state: FSMContext):
    phone = m.contact.phone_number if m.contact else parse_phone(m.text)
    phone = fmt_phone(phone) if phone else None
    if not phone:
        return await m.answer(bad_phone_text(), reply_markup=phone_kb())
    st = await state.get_data()
    await state.clear()
    answers = st.get("answers", {})
    lid = db.add_lead(m.from_user.id, m.from_user.full_name, phone, answers, st.get("estimate", ""))
    await m.answer(tr("✅ Спасибо! Заявка принята, менеджер скоро позвонит.", "✅ Thank you! Request received, a manager will call you soon."),
                   reply_markup=ReplyKeyboardRemove())
    await m.answer(tr("Что дальше?", "What's next?"), reply_markup=kb([[menu_btn()]]))
    summary = "\n".join(f"• {q['text']} {logic.quiz_option_label(q['id'], answers.get(q['id'], ''))}" for q in QS())
    await notify_owner(m.bot, f"🔥 <b>{tr('Новая заявка', 'New lead')} #{lid}</b>\n{m.from_user.full_name}, {phone}\n{summary}\n"
                              f"{tr('Ориентир', 'Estimate')}: {st.get('estimate', '')}", m.chat.id)
