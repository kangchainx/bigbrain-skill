# Bigbrain motion preview

A 24-second, 1920 × 1080, 30 fps bilingual Remotion composition. Claude Opus 5.5 authored the art direction, dialogue and motion source; Codex scaffolded the project, added editable scene registrations and pre-mounting, and checked the preview. This is an illustrative script, not a real agent transcript. Both language versions include a 24-second edit of “City Loop” by wipics (CC0), with loudness normalization and fades. See `public/audio/LICENSE.md`.

Primary visual reference: [zkjays — motion infographics](https://x.com/zkjays/status/2113186873745322233). The implementation uses the official Remotion skills; it does not include the author's private skills, original footage, music or assets.

```sh
npm ci
npm run dev -- --no-open --port 8767
```

Open the URL printed by Studio. Select `BigbrainZH` or `BigbrainEN`; individual scenes are under `Scenes`. Dialogue is in `src/copy.ts`, timing and colors in `src/theme.ts`.

```sh
npm run lint
npx remotion still src/index.ts BigbrainZH out/preview.png --frame=320
```

Regenerate the approved README videos with:

```sh
npx remotion render src/index.ts BigbrainZH ../assets/demo.zh-CN.mp4
npx remotion render src/index.ts BigbrainEN ../assets/demo.en.mp4
```

The README demo assets in `../assets/` use this approved composition: bilingual MP4 files with music and silent GIF previews. Fonts use macOS system fallbacks; typography may differ on other operating systems. See `DESIGN.md` for the scene treatment.

This optional documentation build project uses Node.js and Remotion; it is excluded from skill installation and does not change Bigbrain’s Python standard-library-only runtime. Third-party dependencies retain their own licenses. Zod is overridden to 4.6.6 to address the constrained-collection memory-exhaustion advisory in the version pinned by Remotion.

Remotion 4.0.539 may report a Zod version mismatch because of this security override. Type checking, linting and a still render have been verified with 4.6.6.
