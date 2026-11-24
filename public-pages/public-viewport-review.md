# Public page design and viewport checks

The start branch was tested at [`d071f636`](https://github.com/vedansh-5/visdom-dev/commit/d071f63692460c7223c9066c4fcc513b06fcea45). The combined plans, terms and contact branch was tested at [`c8d2786e`](https://github.com/vedansh-5/visdom-dev/commit/c8d2786e217ffba6b3773644b1896cc241115e87). Each engine ran 936 page, size, account and motion combinations per branch. All measured public layouts passed in Chromium and native macOS WebKit.

## Page by size

Each cell covers signed out and signed in, under normal and reduced motion, in both engines on the combined branch. The letters identify the measured issue and its fix in the key below. The final row uses real browser page zoom with a layout viewport of 720 × 450.

| Viewport | `/` | Pricing | Contact | Terms | Privacy | Cookies | Sign in | Register | 404 |
|---|---|---|---|---|---|---|---|---|---|
| 320 × 568 | Pass H¹ | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 360 × 640 | Pass H¹ | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 375 × 667 | Pass H¹ | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 390 × 844 | Pass H¹ | Pass F | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 414 × 896 | Pass H¹ | Pass F | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 430 × 932 | Pass H¹ | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 667 × 375 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 844 × 390 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 932 × 430 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 768 × 1024 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 820 × 1180 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 1024 × 768 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 1024 × 1366 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 1180 × 820 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 1280 × 720 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 1280 × 800 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 1366 × 768 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 1440 × 900 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 1512 × 982 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 1536 × 864 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 1680 × 1050 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 1920 × 1080 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 1920 × 1200 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 2560 × 1440 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 3440 × 1440 | Pass H² | Pass P | Pass C | Pass T | Pass L | Pass L | Pass A | Pass A | Pass N |
| 1440 × 900 at 200% | Pass H² + Z | Pass P + Z | Pass C + Z | Pass T + Z | Pass L + Z | Pass L + Z | Pass A + Z | Pass A + Z | Pass N + Z |

### What the size table records

| Key | Baseline finding and change | Commit |
|---|---|---|
| H | The hero had 10px pane text and a smaller headline. It now fits its original grid span with two lines or fewer. The lower page has even steps and two featured demo rows. Three native WebKit role selectors grew from 22px to 44px. | [`6a055ffa`](https://github.com/vedansh-5/visdom-dev/commit/6a055ffa14ab8032e2ec309f8695f6ea418b691a) · [`aa4e977b`](https://github.com/vedansh-5/visdom-dev/commit/aa4e977b50708ca5f92178ac38ead791bdd05dec) · [`627cb10f`](https://github.com/vedansh-5/visdom-dev/commit/627cb10ff34f3da43f5a677e24b9b9049a9953e8) |
| P | Pricing cards and comparison now share the header gutters. At 1440px each side went from 128px to 72px. At 2560px each went from 688px to 88px. | [`54d5524d`](https://github.com/vedansh-5/visdom-dev/commit/54d5524dd72653b90e05e2ff0aa79dac17ccd45a) |
| F | Pricing already aligned within 1px at 390px and 414px. Its public font and colors changed at these widths too. | [`54d5524d`](https://github.com/vedansh-5/visdom-dev/commit/54d5524dd72653b90e05e2ff0aa79dac17ccd45a) · [`b2b43e73`](https://github.com/vedansh-5/visdom-dev/commit/b2b43e732703b56b6634b802d723f12b9ad75479) |
| C | The introduction now explains what to send and when to expect a reply. The native WebKit topic selector grew from 23px to 44px. | [`7a5c494c`](https://github.com/vedansh-5/visdom-dev/commit/7a5c494c880df35b2e4e26c5fd5ec9823867047e) · [`de11a5fb`](https://github.com/vedansh-5/visdom-dev/commit/de11a5fb5bf0ee76dc21e599ad89e23435eaf084) · [`affe21fc`](https://github.com/vedansh-5/visdom-dev/commit/affe21fcc179ffd942680586d72b498e6a1c3167) |
| T | Terms uses the public legal layout. Its header preserves the selected plan when returning to registration. | [`b2b43e73`](https://github.com/vedansh-5/visdom-dev/commit/b2b43e732703b56b6634b802d723f12b9ad75479) · [`9bfe215c`](https://github.com/vedansh-5/visdom-dev/commit/9bfe215c672fbe5fcd4c9c1f2c6ab0f81065ef7b) |
| L | The old legal card had a 24px title, a shadow and a second sign-in link. Both notices now have a 38px to 72px heading, the public font and a 70ch maximum text width. | [`b2b43e73`](https://github.com/vedansh-5/visdom-dev/commit/b2b43e732703b56b6634b802d723f12b9ad75479) |
| A | Sign-in and registration labels, notes and validation text now meet the 13px minimum and use the public font and button colors. | [`b2b43e73`](https://github.com/vedansh-5/visdom-dev/commit/b2b43e732703b56b6634b802d723f12b9ad75479) |
| N | The 404 uses the public typography and account-aware navigation. | [`b2b43e73`](https://github.com/vedansh-5/visdom-dev/commit/b2b43e732703b56b6634b802d723f12b9ad75479) |
| Z | At 200% WebKit zoom the wordmark pushed the 720px page to 1302px and two start-page headings wrapped to three lines. The wordmark now fits, the horizontal scroll position stays at zero and the headings fit. | [`d071f636`](https://github.com/vedansh-5/visdom-dev/commit/d071f63692460c7223c9066c4fcc513b06fcea45) · [`731b6e97`](https://github.com/vedansh-5/visdom-dev/commit/731b6e978785753a0ff5c11ff1b9c0aa7b64130d) |

¹ Signed-in `/` opens the existing dashboard. At these six portrait widths it has horizontal overflow, 11 controls below 44px and 12px text. The same results were measured on the previous PR head.

² At these widths the signed-in dashboard still has the same 11 controls below 44px and 12px text. No horizontal overflow was measured. The dashboard source stayed outside this public-page change.

On the start-only branch, `/pricing`, `/contact` and `/terms` reached its public 404 in both account states. The combined branch supplied those three pages.

## Requested changes

| Brief item | Result | Commit |
|---|---|---|
| A. Colour | Training-plot palette, color-coded pane strips and lines, cool class and warm attention scales, three run-status colors, mint and sand sections and a dark teal closing band. Primary actions share one blue. | [`33222581`](https://github.com/vedansh-5/visdom-dev/commit/332225816997ba7d82f929b1f1d4ed73649b6644) · [`6a055ffa`](https://github.com/vedansh-5/visdom-dev/commit/6a055ffa14ab8032e2ec309f8695f6ea418b691a) · [`aa4e977b`](https://github.com/vedansh-5/visdom-dev/commit/aa4e977b50708ca5f92178ac38ead791bdd05dec) |
| B1. What you get | Two alternating rows for live plots and workspace roles, followed by four expandable demos. All six work. | [`aa4e977b`](https://github.com/vedansh-5/visdom-dev/commit/aa4e977b50708ca5f92178ac38ead791bdd05dec) |
| B2. Built in the open | Open-source description beside the copyable `pip install visdom` command. | [`aa4e977b`](https://github.com/vedansh-5/visdom-dev/commit/aa4e977b50708ca5f92178ac38ead791bdd05dec) |
| B3. Headline | Larger type within the same set of panes, including landscape and zoom. | [`6a055ffa`](https://github.com/vedansh-5/visdom-dev/commit/6a055ffa14ab8032e2ec309f8695f6ea418b691a) · [`731b6e97`](https://github.com/vedansh-5/visdom-dev/commit/731b6e978785753a0ff5c11ff1b9c0aa7b64130d) |
| B4. First plot steps | Four equal-height previews, ordered in the document, with the full Python example available on demand. | [`aa4e977b`](https://github.com/vedansh-5/visdom-dev/commit/aa4e977b50708ca5f92178ac38ead791bdd05dec) |
| B5. Closing plot | The example’s four loss values draw once on entry using a scaling SVG clipping rectangle. Reduced motion shows the completed trace immediately. | [`aa4e977b`](https://github.com/vedansh-5/visdom-dev/commit/aa4e977b50708ca5f92178ac38ead791bdd05dec) · [`27edb2b3`](https://github.com/vedansh-5/visdom-dev/commit/27edb2b3ce3365cc6fe830f096856d63f38100b9) |
| B6. Text size | A 13px minimum for readable text in the panes, steps, demos, footer and account forms. Pane titles remain monospace. | [`6a055ffa`](https://github.com/vedansh-5/visdom-dev/commit/6a055ffa14ab8032e2ec309f8695f6ea418b691a) · [`aa4e977b`](https://github.com/vedansh-5/visdom-dev/commit/aa4e977b50708ca5f92178ac38ead791bdd05dec) · [`b2b43e73`](https://github.com/vedansh-5/visdom-dev/commit/b2b43e732703b56b6634b802d723f12b9ad75479) |
| B7. Footer | Three columns, Contact under Product and a scalable full-width wordmark. | [`b2b43e73`](https://github.com/vedansh-5/visdom-dev/commit/b2b43e732703b56b6634b802d723f12b9ad75479) · [`d071f636`](https://github.com/vedansh-5/visdom-dev/commit/d071f63692460c7223c9066c4fcc513b06fcea45) |
| B8. Section motion | One staggered entrance per section item, using opacity and transform. Content is visible without the observer. | [`aa4e977b`](https://github.com/vedansh-5/visdom-dev/commit/aa4e977b50708ca5f92178ac38ead791bdd05dec) · [`27edb2b3`](https://github.com/vedansh-5/visdom-dev/commit/27edb2b3ce3365cc6fe830f096856d63f38100b9) |
| C9. Legal | Shared public headings and reading column on Privacy, Cookies and Terms. | [`b2b43e73`](https://github.com/vedansh-5/visdom-dev/commit/b2b43e732703b56b6634b802d723f12b9ad75479) · [`9bfe215c`](https://github.com/vedansh-5/visdom-dev/commit/9bfe215c672fbe5fcd4c9c1f2c6ab0f81065ef7b) |
| C10. Typeface | Helvetica Neue with local Helvetica and Arial fallbacks on public pages. | [`b2b43e73`](https://github.com/vedansh-5/visdom-dev/commit/b2b43e732703b56b6634b802d723f12b9ad75479) · [`54d5524d`](https://github.com/vedansh-5/visdom-dev/commit/54d5524dd72653b90e05e2ff0aa79dac17ccd45a) · [`7a5c494c`](https://github.com/vedansh-5/visdom-dev/commit/7a5c494c880df35b2e4e26c5fd5ec9823867047e) |
| C11. Pricing margins | Cards, table and header line up at both sides. | [`54d5524d`](https://github.com/vedansh-5/visdom-dev/commit/54d5524dd72653b90e05e2ff0aa79dac17ccd45a) |
| C12. Contact | Workspace and billing guidance, plus a nonbinding estimate of a few days for contributor replies. No address is displayed. | [`7a5c494c`](https://github.com/vedansh-5/visdom-dev/commit/7a5c494c880df35b2e4e26c5fd5ec9823867047e) · [`de11a5fb`](https://github.com/vedansh-5/visdom-dev/commit/de11a5fb5bf0ee76dc21e599ad89e23435eaf084) |
| D. Viewports | Native selector targets, landscape title wraps and zoomed wordmark overflow found and fixed during the size checks. | [`627cb10f`](https://github.com/vedansh-5/visdom-dev/commit/627cb10ff34f3da43f5a677e24b9b9049a9953e8) · [`affe21fc`](https://github.com/vedansh-5/visdom-dev/commit/affe21fcc179ffd942680586d72b498e6a1c3167) · [`731b6e97`](https://github.com/vedansh-5/visdom-dev/commit/731b6e978785753a0ff5c11ff1b9c0aa7b64130d) · [`d071f636`](https://github.com/vedansh-5/visdom-dev/commit/d071f63692460c7223c9066c4fcc513b06fcea45) |
| Branch integration | Signed-off merge of the start branch into the plans branch. | [`c8d2786e`](https://github.com/vedansh-5/visdom-dev/commit/c8d2786e217ffba6b3773644b1896cc241115e87) |

## Palette and contrast

Ratios use WCAG relative luminance in sRGB. Strip labels and primary action text use white. The same ratio applies when the plot draws that color on white. Light grid crossings are listed separately.

| Use | Foreground / background | Ratio |
|---|---|---|
| Loss and primary actions | `#20598b` / `#fff` | 7.33:1 |
| Accuracy | `#216449` / `#fff` | 7.04:1 |
| Learning rate and attention | `#945019` / `#fff` | 6.14:1 |
| Class heatmap title | `#12645f` / `#fff` | 6.97:1 |
| Image batch title | `#984338` / `#fff` | 6.57:1 |
| Gradient norm and GPU memory | `#455c63` / `#fff` | 7.08:1 |
| Secondary loss line | `#16416a` / `#fff` | 10.51:1 |
| Lowest line contrast crossing a grid rule | `#945019` / `#c9d6d5` | 4.11:1 |
| Running | `#216449` / `#e7f3ed` | 6.18:1 |
| Stopped | `#984338` / `#f6e8e4` | 5.50:1 |
| Done | `#16416a` / `#e7f1f7` | 9.17:1 |
| Body on mint steps | `#172a32` / `#e7f3ed` | 13.04:1 |
| Body on sand install section | `#172a32` / `#faf0df` | 13.15:1 |
| Body on pale blue plan card | `#172a32` / `#e7f1f7` | 12.96:1 |
| Secondary text on paper | `#455c63` / `#f8faf8` | 6.75:1 |
| Footer headings and wordmark | `#bad1d1` / `#152c33` | 9.12:1 |
| Pitch and run detail text | `#e5f1f0` / `#152c33` | 12.62:1 |
| Readout on dark background | `#fff` / `#152c33` | 14.58:1 |
| Closing band text | `#fff` / `#184c4a` | 9.67:1 |
| Input border on white | `#71898c` / `#fff` | 3.71:1 |

## Interaction and build checks

Both builds passed lint and the production build. The touched test files passed, with 29 tests on the start branch and 42 on the integrated branch. All six CI jobs passed on both heads. The mobile Lighthouse runs scored 86/100 and 84/100 for performance, respectively, and 100/100 for accessibility on both. Largest contentful paint was 3.3s and 3.5s. Both measured zero layout shift and zero blocking time.

Chromium checked keyboard menu opening, focus wrapping, Escape and focus restoration on small viewports. All 25 sizes were exercised for plot interaction, all six feature demos and keyboard run selection. Worked examples included revoking and restoring a key, changing a member role, sorting, copying and navigating a chart. Touch events ran in Chromium device emulation. The chart was also verified with the viewport observer unavailable.

Native macOS WebKit checked real page zoom, browser-trusted mouse and keyboard input, and the operating-system motion preference as overridden for the test web view. It verified chart point and run selection, menu open and focus return, one normal-motion chart draw and a fully visible static trace under reduced motion. The system-wide user preference was left alone.

Local account, pricing and contact fixtures supplied the data. Firefox was unavailable. Physical touchscreen devices, screen-reader speech output, live delivery and production traffic were outside this check. The few-days reply estimate is editorial guidance based on contributor availability.
