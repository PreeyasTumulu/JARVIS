# Speech recognition benchmark (cuda)

Run on 2026-10-20 13:23. 30 Jarvis commands spoken by Piper with background noise at about 20 dB SNR, transcribed with Jarvis's own settings (beam 1, the command hint). Word error rate counts digits and spelled numbers as equal.

Regenerate with `uv run python scripts/benchmark_stt.py`.

| Model | Word error rate | Median time | Slowest | Load |
|---|---|---|---|---|
| `small.en` | 6.8% | 135 ms | 173 ms | 3.0 s |
| `base.en` | 7.7% | 55 ms | 108 ms | 0.7 s |

## `small.en` mistakes

- 'search youtube for lofi music' -> 'Search YouTube for low fee music.'
- 'call Ravi' -> 'Gold Ravi.'
- 'next song' -> 'Next solve.'
- "reply that I'll send the report tonight" -> "Reply that I'll send a report tonight."
- 'remember that my manager is Ravi' -> 'Remember that my manager is rapping.'
- 'convert one hundred dollars to rupees' -> 'Convert $100 to Rupees.'
- 'show the logs of the postgres container' -> 'Show the logs of the PostGiz container.'

## `base.en` mistakes

- "message mom that I'll be late" -> "Message mum that I'll be late."
- 'call Ravi' -> 'Cool rabbit.'
- 'next song' -> 'Next, solve.'
- "reply that I'll send the report tonight" -> "Reply that I'll send a report tonight."
- 'remember that my manager is Ravi' -> 'Remember that my manager is rapping.'
- 'convert one hundred dollars to rupees' -> 'Convert $100 to rupees.'
- 'show the logs of the postgres container' -> 'Show the logs of the posters container.'
