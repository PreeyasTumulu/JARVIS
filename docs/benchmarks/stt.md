# Speech recognition benchmark (cpu)

Run on 2026-10-20 12:52. 30 Jarvis commands spoken by Piper with background noise at about 20 dB SNR, transcribed with Jarvis's own settings (beam 1, the command hint). Word error rate counts digits and spelled numbers as equal.

Regenerate with `uv run python scripts/benchmark_stt.py`.

| Model | Word error rate | Median time | Slowest | Load |
|---|---|---|---|---|
| `small.en` | 11.2% | 1433.5 ms | 2287 ms | 4.3 s |
| `base.en` | 8.0% | 442.5 ms | 526 ms | 0.7 s |
| `distil-small.en` | 17.4% | 1303.5 ms | 1485 ms | 518.7 s |

## `small.en` mistakes

- 'search youtube for lofi music' -> 'Search YouTube for Loafy Music.'
- 'call Ravi' -> 'Gold Ravi'
- "reply that I'll send the report tonight" -> "Reply that I'll send a report tonight."
- 'remember that my manager is Ravi' -> 'Remember that my manager is RAVID.'
- 'convert one hundred dollars to rupees' -> 'Convert $100 to Rupees.'
- 'show the logs of the postgres container' -> 'Show the logs of the Posters container.'
- 'stop' -> "It's off."

## `base.en` mistakes

- 'search youtube for lofi music' -> 'Search YouTube for Lo-fi music.'
- 'call Ravi' -> 'Call Robbie.'
- "reply that I'll send the report tonight" -> "Reply that I'll send a report tonight."
- 'convert one hundred dollars to rupees' -> 'Convert $100 to Rupees'
- 'show the logs of the postgres container' -> 'Show the logs of the Postures container.'
- 'stop' -> ''

## `distil-small.en` mistakes

- 'open notepad' -> 'Open Note Herr.'
- 'search youtube for lofi music' -> 'Search YouTube for Loafie Music.'
- 'call Ravi' -> 'Cool Rabbit.'
- 'next song' -> 'Next Soul.'
- "reply that I'll send the report tonight" -> "Reply that I'll send a report tonight."
- 'remember that my manager is Ravi' -> 'Remember that my manager is Ravith.'
- 'convert one hundred dollars to rupees' -> 'Convert $100 to rupees.'
- 'show the logs of the postgres container' -> 'Show the logs of the postures container.'
- 'open VS Code' -> 'Open the S code.'
- 'type hello world in Notepad' -> 'Type hello, world in NoTad.'
- 'stop' -> ''
