function chapterEscape(value) { return String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character])); }

export function learningChapter(lesson) {
  if (!lesson) return '';
  const esc=chapterEscape, list=rows=>(rows||[]).map(row=>`<li>${esc(row)}</li>`).join('');
  const example=lesson.worked_example||{}, alternative=lesson.counterexample||{}, task=lesson.practice||{};
  return `<article class="learning-chapter" data-lesson="${esc(lesson.id)}">
    <header class="chapter-header"><p class="eyebrow">Разбор темы · ${esc(lesson.estimated_minutes)} минут</p><h3>${esc(lesson.title)}</h3><p>${esc(lesson.lead)}</p></header>
    <div class="chapter-goals"><h4>Что ты научишься замечать</h4><ul>${list(lesson.goals)}</ul></div>
    <div class="chapter-sections">${(lesson.sections||[]).map((section,index)=>`<details${index===0?' open':''}><summary>${esc(section.title)}</summary>${(section.paragraphs||[]).map(text=>`<p>${esc(text)}</p>`).join('')}</details>`).join('')}</div>
    <section class="chapter-example"><p class="eyebrow">Разберём на примере</p><h4>${esc(example.title)}</h4><p>${esc(example.setup)}</p><ol>${list(example.steps)}</ol><p class="chapter-example-result">${esc(example.result)}</p></section>
    <details class="chapter-counterexample"><summary>Когда нужно другое решение</summary><p>${esc(alternative.setup)}</p><p>${esc(alternative.why_different)}</p><p><strong>Что сделать:</strong> ${esc(alternative.better_action)}</p></details>
    <details class="chapter-errors"><summary>Типичные ошибки и как их исправить</summary><dl>${(lesson.common_errors||[]).map(error=>`<dt>${esc(error.habit)}</dt><dd>${esc(error.correction)}</dd>`).join('')}</dl></details>
    <section class="chapter-practice"><h4>Проверь в своей игре</h4><div class="chapter-practice-grid">${[['before','Перед матчем'],['during','Во время игры'],['after','При просмотре повтора'],['success','Как понять, что получилось']].map(([key,label])=>`<div><h5>${label}</h5><p>${esc(task[key])}</p></div>`).join('')}</div></section>
    <section class="chapter-self-check"><h4>Объясни своими словами</h4><p>Сначала сформулируй ответ, затем открой разбор.</p>${(lesson.self_check||[]).map(check=>`<details><summary>${esc(check.question)}</summary><p>${esc(check.answer)}</p></details>`).join('')}</section>
    <p class="chapter-takeaway"><strong>Запомни:</strong> ${esc(lesson.takeaway)}</p>
  </article>`;
}
