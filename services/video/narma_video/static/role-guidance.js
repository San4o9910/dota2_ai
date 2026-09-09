// A role's practice priorities are guidance, not observations about a match.
export function roleGuidance(context) {
  if (!context || !Number.isInteger(context.position) || context.position < 1 || context.position > 5) return null;
  const element = (tag, text) => { const value = document.createElement(tag); value.textContent = text; return value; };
  const card = document.createElement('section');
  card.className = 'role-guidance';
  card.dataset.position = String(context.position);
  card.setAttribute('aria-label', `Задачи позиции: ${context.label}`);
  card.append(element('h3', context.label), element('p', context.lane_priority), element('p', context.farm_policy));
  const details = document.createElement('details');
  details.append(element('summary', 'Карта, предметы и проверка после игры'));
  for (const [label, key] of [['Карта', 'map_priority'], ['Бой', 'fight_priority'], ['Предметы', 'item_priority'], ['Проверка решения', 'review_question'], ['В следующей игре', 'next_game_action'], ['Как проверить', 'measurement']]) {
    if (!context[key]) continue;
    const row = document.createElement('p'); row.append(element('strong', `${label}. `), document.createTextNode(context[key])); details.append(row);
  }
  card.append(details);
  return card;
}
