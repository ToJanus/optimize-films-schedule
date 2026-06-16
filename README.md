# Optimize Films Schedule

Narzędzie CLI w Pythonie do wyliczania wszystkich możliwych planów obejrzenia filmów w jednym dniu. Na wejściu podajesz filmy, seanse, kina, priorytety, czas reklam, czasy dojazdu oraz marginesy bezpieczeństwa, a na wyjściu dostajesz posortowaną listę możliwych terminarzy.

## Model danych

Konfiguracja jest plikiem JSON. Przykład znajduje się w `examples/sample_day.json`.

Najważniejsze sekcje:

- `priorities` — dowolna liczba kategorii ważności. Im większa liczba, tym mocniej dany film wpływa na sortowanie wyników.
- `films` — lista filmów z czasem trwania i przypisaną kategorią ważności.
- `cinemas` — lista kin; `ads_minutes` określa reklamowy bufor na początku seansu w danym kinie, a opcjonalne `address` pozwala zapisać dokładny adres kina.
- `screenings` — lista seansów z godziną z repertuaru (`starts_at`). Opcjonalne `margin_before_minutes` i `margin_after_minutes` nadpisują domyślne marginesy dla konkretnego seansu.
- `places` — opcjonalna lista dodatkowych miejsc (np. dom, hotel, dworzec) z `id`, nazwą i opcjonalnym dokładnym adresem `address`. Takie miejsce może być początkiem albo końcem dnia.
- `constraints` — opcjonalne ograniczenia: `required_films` wymusza wybrane filmy, `required_film_cinemas` wymusza pary film+kino, `start_location_id` ustawia punkt startu, a `end_location_id` punkt końcowy. Wymuszenia są nadrzędne wobec punktów za priorytety tak długo, jak da się je spełnić czasowo; jeśli nie da się spełnić wszystkich, optimizer pokazuje warianty spełniające największą możliwą liczbę wymuszeń, a potem sortuje je priorytetami.
- `travel_times` — ręczna macierz czasów przejazdu między kinami oraz dodatkowymi miejscami z `places`. To najprostsza darmowa opcja, bez zależności od zewnętrznych API i limitów map.


Przykład ograniczeń w JSON:

```json
{
  "places": [
    {"id": "dom", "name": "Dom", "address": "ul. Domowa 1, Warszawa"}
  ],
  "constraints": {
    "required_films": ["film-3"],
    "required_film_cinemas": [
      {"film_id": "film-4", "cinema_id": "kino-c"}
    ],
    "start_location_id": "dom",
    "end_location_id": "dom"
  }
}
```

`start_location_id` i `end_location_id` mogą wskazywać zarówno element z `places`, jak i samo kino z `cinemas`. Dla tych punktów trzeba dodać odpowiednie przejazdy w `travel_times.times`, chyba że wystarcza `default_minutes`.

Optimizer zakłada, że godzina seansu to godzina z repertuaru, a właściwy film zaczyna się po reklamach danego kina. Czas zablokowany dla seansu liczony jest od `starts_at + ads_minutes - margin_before_minutes` do `starts_at + ads_minutes + duration_minutes + margin_after_minutes`.

## Uruchomienie

```bash
python -m film_schedule.cli examples/sample_day.json
```

Wynik tekstowy wygląda tak:

```text
1. score=250, filmy=4, dojazdy=35 min, czekanie=275 min: Film 1 o 10:00 (Kino A); Film 2 o 12:50 (Kino A); Film 3 o 17:00 (Kino A); Film 4 o 21:20 (Kino C)
```

Możesz też dostać JSON do dalszego przetwarzania:

```bash
python -m film_schedule.cli examples/sample_day.json --format json --limit 10
```

Jeśli chcesz pokazać tylko warianty, które zawierają każdy zdefiniowany film dokładnie raz, dodaj:

```bash
python -m film_schedule.cli examples/sample_day.json --all-films
```

Możesz ograniczyć okno oglądania, podając najwcześniejszy start filmu i najpóźniejszy koniec filmu w formacie `HH:MM`:

```bash
python -m film_schedule.cli examples/sample_day.json --earliest-start 10:00 --latest-end 23:30
```

Wyniki możesz zapisać do pliku opcją `--output`. Program zapisze jeden zbiorczy plik w wybranym formacie oraz utworzy obok niego podkatalog `<nazwa_pliku>_records`, w którym każdy pojedynczy terminarz trafi do osobnego pliku:

```bash
python -m film_schedule.cli examples/sample_day.json --format json --limit 10 --output results/day.json
```

## Sortowanie wyników

Wyniki są sortowane kolejno po:

1. największym wyniku punktowym z priorytetów,
2. największej liczbie obejrzanych filmów,
3. najmniejszym łącznym czasie dojazdów,
4. najmniejszym łącznym czasie czekania,
5. wcześniejszej godzinie rozpoczęcia planu.

## Automatyczne czasy dojazdu

Na start używana jest ręczna macierz `travel_times`, bo jest przewidywalna, darmowa i działa offline. W przyszłości można dodać importer z API map, np. OpenStreetMap/OSRM albo komercyjnego API, ale wtedy dochodzą limity, klucze API, cache oraz niejednoznaczność adresów kin.
