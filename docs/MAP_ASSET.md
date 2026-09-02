# Локальный ассет карты Dota 2

NARMA VISION использует карту из установленного клиента, но не публикует графику Valve в GitHub.

## Быстрый вариант через Source 2 Viewer

1. Установите [Source 2 Viewer](https://s2v.app).
2. Откройте Dota 2 через Game Explorer или файл:

   ```text
   <SteamLibrary>/steamapps/common/dota 2 beta/game/dota/pak01_dir.vpk
   ```

3. В VPK найдите `materials/overviews/dota.vmat_c`.
4. Откройте материал и перейдите к связанной текстуре minimap/overview.
5. Экспортируйте текстуру в PNG без изменения ориентации.
6. Сохраните результат как:

   ```text
   public/generated/dota/7.41/minimap.png
   ```

7. Запустите `npm run dev` и проверьте, что подписи Roshan, Tormentor, Wisdom и Twin Gates совпадают с изображением.

## Почему файла нет в Git

Репозиторий публичный. Экспорт содержит графику Valve, поэтому папка `public/generated/dota/` намеренно исключена из Git. В коде остаются только координаты объектов и логика слоёв.

## Координаты

Статические координаты взяты из:

- [dota-interactive-map, mapdata 7.41](https://github.com/leamare/dota-interactive-map/blob/bc73d0e3ea6a421d43780a017aa92e0288c939b5/assets/data/741/mapdata.json)
- лицензия исходного fixture: ISC;
- преобразование мира в проценты задаётся одной функцией `worldToPercent`.

Match-specific координаты вардов и смертей берутся из parsed payload OpenDota.

## Чего этот слой пока не обещает

- положение каждого живого героя в любую секунду;
- положение каждого lane creep;
- HP, mana и cooldown по каждому тику;
- точные зоны видимости с учётом деревьев и высот.

Эти данные потребуют локального разбора полного `.dem`; до этого интерфейс явно подписывает расчётные элементы как модель.
