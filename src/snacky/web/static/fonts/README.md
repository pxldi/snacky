# Fonts

Self-hosted so the Content-Security-Policy needs no external font source.
All files are subsets of fonts under the SIL Open Font License 1.1.

| File | Source | Version | CSS family |
| --- | --- | --- | --- |
| `bricolage-grotesque-extrabold.woff2` | Bricolage Grotesque ExtraBold | 1.001 | Snacky Display (800) |
| `fira-sans-condensed-regular.woff2` | Fira Sans Condensed Regular | 4.301 | Snacky Text (400) |
| `fira-sans-condensed-bold.woff2` | Fira Sans Condensed Bold | 4.301 | Snacky Text (700) |
| `fira-sans-compressed-heavy.woff2` | Fira Sans Compressed Heavy | 4.301 | Snacky Claim (900) |

Licences: `OFL-Bricolage-Grotesque.txt`, `OFL-Fira-Sans.txt`.

Fira declares the Reserved Font Name "Fira". Subsetting makes a Modified
Version, so the three Fira files carry the internal family names "Snacky Text"
and "Snacky Claim" and no longer use "Fira" in their name tables. Bricolage
Grotesque declares no Reserved Font Name and keeps its own names.

## Subset

Basic Latin, Latin-1 Supplement, U+20AC, U+201A, U+201C, U+201E, U+2018,
U+2019, U+201D, U+2013, U+2014, U+2026, U+202F, U+2248, U+00D7, U+00B7,
U+2022. None of the fonts has U+2713. Layout features kept: kern, tnum, lnum
(dropped by the subsetter, the default figures are already lining), liga,
ccmp, locl, mark, mkmk.

```sh
uvx --from 'fonttools[woff]' pyftsubset SOURCE.ttf \
  --unicodes="U+0020-007E,U+00A0-00FF,U+20AC,U+201E,U+201C,U+201A,U+2018,U+2019,U+201D,U+2013,U+2014,U+2026,U+202F,U+2248,U+00D7,U+00B7,U+2022" \
  --layout-features="kern,tnum,lnum,liga,ccmp,locl,mark,mkmk" \
  --flavor=woff2 --name-IDs='*' --no-hinting --output-file=OUT.woff2
```

The Fira files were then renamed by setting name IDs 1, 2, 3, 4 and 6 and
removing IDs 16, 17, 21, 22 and 25 with fontTools.
