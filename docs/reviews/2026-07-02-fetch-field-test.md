# PIM 20-Source Fetch Field Test

- Ran at: `2026-07-03T15:40:12.403802+00:00`
- Server: `http://127.0.0.1:8000`
- Source count: `20`
- OK / warning / empty / error: `16 / 3 / 1 / 0`
- Would-store total: `130`

| # | Source | Type | Status | Collected | Valid | Would Store | Warning/Error | Samples |
|---:|---|---|---|---:|---:|---:|---|---|
| 1 | 36kr | website | warning | 20 | 0 | 0 |  |  |
| 2 | BBC 中文 | website | ok | 15 | 10 | 10 |  | 美国建国250年：五个中美交往的历史细节与默契; “武官治港”：警队进驻官方要职，想体现中国维稳逻辑？; 乙女游戏：在“2.5次元”中，谈一场模糊虚拟与现实的恋爱 |
| 3 | CNN | website | ok | 1 | 1 | 1 |  | Calculators |
| 4 | Engadget | website | warning | 20 | 0 | 0 |  |  |
| 5 | Lex Fridman | youtube | empty | 0 | 0 | 0 |  |  |
| 6 | RayDalio | x | ok | 20 | 7 | 7 |  | By checks, I mean people who check on other people to make sure they're performi...; For instance, if you want to have a healthy life, you shouldn’t have twelve saus...; Copyright |
| 7 | Reuters | website | warning | 0 | 0 | 0 | 需要登录后才能访问（Discovery listing fetch failed: https://www.reuters.com/） |  |
| 8 | The Verge | website | ok | 10 | 10 | 10 |  | While you’re watching the World Cup, the feds may be watching you; This slim camera has a transparent LCD screen for a viewfinder; I finally got my Trump phone |
| 9 | X：AI Safety Memes (@AISafetyMemes) | x | ok | 18 | 11 | 11 |  | "underneath, the model is basically reasoning in its own compressed shorthand th...; Look at this chart, but imagine Mythos is finding vulnerabilities in the human g...; RT @AISafetyMemes: AI just solved not one, but ***9*** unsolved math problems. ... |
| 10 | X：AK (@_akhaliq) | x | ok | 18 | 18 | 18 |  | RT @silverbottlep: Accepted to #ECCV2026! 🎉 We've also released the code, it sho...; RT @vanstriendaniel: Coding agents are real users of the Hub now i.e. Claude Cod...; RT @zRdianjiao: Here is the reference doc with an example of using Claude Code w... |
| 11 | X：Andrej Karpathy (@karpathy) | x | ok | 7 | 1 | 1 |  | RT @Etched: We're coming out of stealth. We've built our first racks after a su... |
| 12 | X：Anthropic (@AnthropicAI) | x | ok | 10 | 5 | 5 |  | RT @claudeai: Fable 5 is back. https://t.co/9RTGUCcPHy; On Friday, June 12, the US government applied export controls to our newest mode...; We’ve received notice that the Department of Commerce has lifted export controls... |
| 13 | X：Artificial Analysis (@ArtificialAnlys) | x | ok | 4 | 4 | 4 |  | On Monday, Artificial Analysis brought together our largest SF community gatheri...; Fish Audio has recently released S2.1 Pro and is making it available for free vi...; Reve 2.0 debuts at #2 on the Artificial Analysis Text to Image Leaderboard, behi... |
| 14 | X：Astronaut (@Astronaut_1216) | x | ok | 13 | 13 | 13 |  | A bun-workspaces monorepo that screens US equities with an institutional-flow si...; Coze真的是中国最强Agent来着; 也给大家分享一些提示词 |
| 15 | X：Berry Xia (@berryxia) | x | ok | 16 | 16 | 16 |  | \| English; ❤️ https://t.co/kvJ2C4cGk8; Computer Science > Machine Learning |
| 16 | X：ChatGPT (@ChatGPTapp) | x | ok | 11 | 2 | 2 |  | Questions about dollars. Answers that just make sense.; RT @adamhfry: This week's ChatGPT new feature drop - June 26: 1/ New dictation ... |
| 17 | X：Claude (@claudeai) | x | ok | 11 | 10 | 10 |  | Squidsoup is a collective of artists and designers who make immersive experience...; A conversation with Boris Cherny and Cat Wu on the path from Claude Code to Clau...; Announcing Built with Claude: Life Sciences, a global virtual hackathon. |
| 18 | X：Claude Devs (@ClaudeDevs) | x | ok | 8 | 8 | 8 |  | We've raised Claude Platform API rate limits for all users and simplified the ti...; Artifacts in Claude Code are now also available on Pro and Max plans.; RT @claudeai: Announcing Built with Claude: Life Sciences, a global virtual hack... |
| 19 | X：Cloudflare Developers (@CloudflareDev) | x | ok | 10 | 5 | 5 |  | RT @irvinebroque: memory observability for Workers and Durable Objects is here ...; RT @rohinlohe: The Internet’s first economic model was catered around human atte...; Such an amazing turnout this morning in SF! |
| 20 | X：Deedy Das (@deedydas) | x | ok | 18 | 9 | 9 |  | RT @deedydas: Top 20 Startups by Web Traffic founded since 2020 1. DeepSeek 2. ...; Top 20 Startups by Web Traffic founded since 2020; Had one of the most surreal weeks. We got to host and chat with Ravi Ashwin (@as... |

## Notes

- This report is generated from `/api/sources/{id}/dry-run`; it does not write content rows.
- `empty` and `warning` rows need manual review against the source page and current publishing cadence.
- Auth-required sources may need a fresh Auth Bundle or browser session before rerunning.
