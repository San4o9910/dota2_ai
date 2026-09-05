import { AnalysisReportV1Schema, type AnalysisReportV1, type EvidenceBundleV1 } from "@/lib/analysis/contracts";

const QUESTIONS = {
  fight: { title: "Разбор драки", body: "Остановите реплей перед входом в драку. Какую цель вы хотели получить? Что было видно вашей команде? Сопоставьте своё решение с результатом в таблице." },
  objective: { title: "Событие на карте", body: "В журнале зафиксировано событие с объектом. Проверьте, где находился ваш герой перед этим моментом и какую задачу вы выполняли." },
  economy: { title: "Экономика матча", body: "Золото и опыт показывают состояние команд на выбранной отметке. Посмотрите предшествующий отрезок реплея: куда вы двигались и какие ресурсы получили?" },
  player: { title: "Показатели героя", body: "Это итоговые показатели выбранного героя. Они помогают выбрать эпизод для просмотра, но не объясняют причину решения или смерти." },
  team: { title: "Показатели команды", body: "Это суммарные показатели команды. Для оценки вашего решения нужен конкретный эпизод со своей камеры." },
  match: { title: "Итог матча", body: "Результат зафиксирован в данных матча. Для разбора решения выберите событие на хронологии и проверьте доступную игроку информацию." },
} as const;

/** Publish only application-owned explanations. The model ranks evidence;
 * it cannot smuggle an unsupported causal story through a valid numeric claim.
 * This also provides safe presentation for legacy saved reports. */
export function compileCoachingPresentation(report: AnalysisReportV1, bundle: EvidenceBundleV1): AnalysisReportV1 {
  const evidence = new Map(bundle.evidence.map(e => [e.id,e]));
  return AnalysisReportV1Schema.parse({
    ...report,
    items: report.items.map(item => {
      const references = item.claims.map(c => evidence.get(c.evidenceId)).filter(e => e !== undefined);
      const primary = references.find(e => e.time !== null) ?? references[0];
      let copy: {title:string;body:string} = QUESTIONS[primary?.kind ?? "match"];
      if(primary?.id.includes("first_blood"))copy={title:"Стартовая драка",body:"Смерть героя зафиксирована в журнале. Посмотрите начало эпизода: участвовал ли ваш герой, какую информацию вы успели получить и можно ли было выйти из драки?"};
      else if(primary?.id.includes("tower"))copy={title:"Падение башни",body:"Перейдите к моменту падения башни. Проверьте своё действие в это время: защита, обмен на другой объект или фарм. Что команда получила в ответ?"};
      else if(primary?.id.includes("tormentor"))copy={title:"Tormentor",body:"Посмотрите подготовку к Tormentor. Кто участвовал, сколько занял подход и что происходило на линиях в это время?"};
      else if(primary?.id.includes("roshan"))copy={title:"Roshan",body:"Посмотрите минуту перед Roshan. Какие линии были пропушены и какие противники были видны? Эти детали нужно проверить по реплею."};
      const start = primary?.time?.type === "point" ? primary.time.seconds : primary?.time?.type === "window" ? primary.time.startSeconds : null;
      return {...item,kind:"advice",...copy,time:primary?.time ?? null,stage:start===null ? "overall" : start<=720 ? "laning" : start<=1800 ? "mid" : "late",confidence:"low",limitations:["Причина ошибки и намерение игрока не установлены по сводке матча."]};
    }),
    limitations:["Точные перемещения, туман войны, состояние способностей и камера игрока требуют полного реплея.","Вопросы помогают проверить решение; они не являются подтверждённым диагнозом ошибки."],
  });
}
