"""Квиз-калькулятор: 4 вопроса → ориентир цены → телефон → заявка менеджеру."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

import data
import db
import logic
from handlers.common import fmt_phone, MENU_BTN, kb, notify_owner, parse_phone, phone_kb

router = Router()
QS = data.QUIZ["questions"]


class Quiz(StatesGroup):
    answering = State()
    phone = State()


def q_view(i: int):
    q = QS[i]
    rows = [[(o[1], f"qa:{i}:{o[0]}")] for o in q["options"]]
    rows.append([("⬅️ Назад", f"qb:{i}")] if i else [MENU_BTN])
    return f"<b>{data.QUIZ['title']}</b> · вопрос {i + 1} из {len(QS)}\n\n{q['text']}", kb(rows)


@router.callback_query(F.data == "m:quiz")
async def quiz_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(Quiz.answering)
    await state.update_data(answers={})
    text, markup = q_view(0)
    await c.message.edit_text(f"{data.QUIZ['company']}\nОтветьте на {len(QS)} вопроса — покажу примерную стоимость.\n\n" + text,
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
    answers[QS[i]["id"]] = oid
    await state.update_data(answers=answers)
    if i + 1 < len(QS):
        text, markup = q_view(i + 1)
        await c.message.edit_text(text, reply_markup=markup)
        return await c.answer()
    est = logic.quiz_estimate(answers)
    est_s = f"{logic.money(est[0])} – {logic.money(est[1])}" if est else "рассчитает менеджер"
    await state.update_data(estimate=est_s)
    await state.set_state(Quiz.phone)
    summary = "\n".join(f"• {q['text']} {logic.quiz_option_label(q['id'], answers.get(q['id'], ''))}" for q in QS)
    await c.message.edit_text(f"{summary}\n\n💰 Ориентир: <b>{est_s}</b>\n\nТочную смету бесплатно посчитает прораб после замера.")
    await c.message.answer("Оставьте телефон — перезвоним в течение 15 минут:", reply_markup=phone_kb())
    await c.answer()


@router.message(Quiz.phone)
async def quiz_phone(m: Message, state: FSMContext):
    phone = m.contact.phone_number if m.contact else parse_phone(m.text)
    phone = fmt_phone(phone) if phone else None
    if not phone:
        return await m.answer("Не похоже на номер. Нажмите кнопку или напишите, например +7 999 123-45-67", reply_markup=phone_kb())
    st = await state.get_data()
    await state.clear()
    answers = st.get("answers", {})
    lid = db.add_lead(m.from_user.id, m.from_user.full_name, phone, answers, st.get("estimate", ""))
    await m.answer("✅ Спасибо! Заявка принята, менеджер скоро позвонит.", reply_markup=ReplyKeyboardRemove())
    await m.answer("Что дальше?", reply_markup=kb([[MENU_BTN]]))
    summary = "\n".join(f"• {q['text']} {logic.quiz_option_label(q['id'], answers.get(q['id'], ''))}" for q in QS)
    await notify_owner(m.bot, f"🔥 <b>Новая заявка #{lid}</b>\n{m.from_user.full_name}, {phone}\n{summary}\n"
                              f"Ориентир: {st.get('estimate', '')}", m.chat.id)
