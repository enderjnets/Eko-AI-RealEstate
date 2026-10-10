# instagram-agent-skill (MIT) — what Eko AI Realtors took from it

Source: https://github.com/Jakeschincariol/instagram-agent-skill, commit
`d03c56be598be770c60b201f94237e5d1a4268a6` (13-sep-2026). Audited on
10-oct-2026: prompt files plus six standard-library Python scripts, no network
calls, no hooks, no MCP servers. Not installed; three ideas adapted into
`backend/app/services/content_craft.py`:

- **Hook formulas** (`skills/ig-reel/hooks.json`): 12 of the 26 kept, reworded
  for a synthetic narrator speaking for licensed agents, plus our own
  "legend, then truth". Dropped: every formula that needs a first-person story,
  an invented figure, a date, or an audience picked by who they are.
- **Caption preview rule** (`skills/ig-caption`): the point of a caption has to
  fit in the first ~125 characters, before Instagram's "more".
- **Machine-written phrases** (`skills/ig-human/slop.json`): a curated subset,
  without words that are honest real-estate vocabulary or that our own fixed
  lines use.

## Licence of the original

MIT License

Copyright (c) 2026 Jake Schincariol

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
