#!/bin/sh
# Synthetic speech clips for the end-to-end check, made with macOS `say` (the Samantha, Milena and
# Lesya voices) and ffmpeg. The clips are not committed; run this on a Mac:
#   sh monitor/tests/audio/make_samples.sh <out dir>
# then upload them where the box can read them and run, on the box:
#   ee-monitor scan-url <url of en_name.m4a> en       -> a name hit "Taras Maslov"
#   ee-monitor scan-url <url of en_ru.m4a> en         -> a language hit (ru) in an English source
#   ee-monitor scan-url <url of ru_name.m4a> ru       -> a name hit "Тарасу Маслову", no language hit
#   ee-monitor scan-url <url of ru_uk.m4a> ru         -> a language hit (uk)
#   ee-monitor scan-url <url of en_terrace.m4a> en    -> at most a low-confidence look-alike
set -eu
OUT=${1:-./samples}
mkdir -p "$OUT"
cd "$OUT"
EN="Samantha"
say -v "$EN" -o en_name.aiff "Good afternoon. Today the Secretary-General met representatives of civil society, including Taras Maslov, who spoke about humanitarian access in the region. We will now take questions from the press."
say -v "$EN" -o en_a.aiff "Thank you. Let me now give the floor to our colleague from the delegation."
say -v Milena -o ru_b.aiff "Уважаемые коллеги, позвольте мне сказать несколько слов о ситуации в регионе. Мы считаем, что необходимо продолжать переговоры."
say -v "$EN" -o en_c.aiff "Thank you very much. The next speaker on my list is the representative of France."
say -v Milena -o ru_name.aiff "Сегодня министр встретился с делегацией и отдельно поблагодарил Тараса Маслова за подготовку визита. Следующая встреча запланирована на понедельник."
say -v Milena -o ru_a.aiff "Добрый день. Начинаем брифинг по итогам недели."
say -v Lesya -o uk_b.aiff "Шановні колеги, дякую за запрошення. Україна готова до діалогу, але лише на основі міжнародного права."
say -v Milena -o ru_c.aiff "Спасибо. Переходим к следующему вопросу."
say -v "$EN" -o en_terrace.aiff "After the summit the leaders had lunch on the terrace overlooking the river, and then returned to the hall."
for f in *.aiff; do ffmpeg -v error -y -i "$f" -ac 1 -ar 22050 "${f%.aiff}.wav"; done
cat_wavs() { out=$1; shift; printf "file '%s'\n" "$@" > list.txt; ffmpeg -v error -y -f concat -safe 0 -i list.txt -c:a aac -b:a 64k "$out"; }
cat_wavs en_ru.m4a en_a.wav ru_b.wav en_c.wav
cat_wavs ru_uk.m4a ru_a.wav uk_b.wav ru_c.wav
for f in en_name ru_name en_terrace; do ffmpeg -v error -y -i $f.wav -c:a aac -b:a 64k $f.m4a; done
rm -f *.aiff *.wav list.txt
ls -la
