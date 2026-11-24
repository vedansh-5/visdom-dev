# Public palette and footer verification

The public hero has six strip colors. Learning rate uses deep cyan. Sample batches and attention maps use raspberry. The confusion matrix stays teal. The install field is ice blue and the steps field is mint. The footer uses the start page’s actual loss, accuracy, heatmap and digit samples.

## Commits

| Item | Change | Commit |
|---|---|---|
| 1 | Hero, steps, install field, stopped runs and account errors | [`5acfa79f`](https://github.com/vedansh-5/visdom-dev/commit/5acfa79f840d9812f20733336b6a416715ad0d2b) |
| 1 | Password recovery and other public notifications | [`9c2ed5c6`](https://github.com/vedansh-5/visdom-dev/commit/9c2ed5c6663cd5b46de6a87a755fae0efb3deea2) |
| 1 | Contact field validation and send errors | [`c7a27839`](https://github.com/vedansh-5/visdom-dev/commit/c7a278391ff0007d06a0e7a152575ba66f5006dd) |
| 2 | Static plot-filled footer, shared tile data and flat fallback | [`221cdb03`](https://github.com/vedansh-5/visdom-dev/commit/221cdb039118c24d740cb022cf88989b235ca244) |
| Integration | Signed-off merge of the start branch into plans, terms and contact | [`111026ec`](https://github.com/vedansh-5/visdom-dev/commit/111026ecc37f5203f35b203eef6a0e137296dffa) |

## Palette and contrast

Ratios use WCAG relative luminance in sRGB. The white-on-strip and line-on-white ratios are equal. The graph rule, status and field rows use the actual colors behind those elements.

| Use | Colors | Ratio |
|---|---|---:|
| Loss and primary actions | `#20598b` / `#fff` | 7.33:1 |
| Accuracy | `#216449` / `#fff` | 7.04:1 |
| Confusion matrix and class predictions | `#12645f` / `#fff` | 6.97:1 |
| Learning rate and the second watcher avatar | `#006e86` / `#fff` | 5.87:1 |
| Image batches and attention | `#a3245a` / `#fff` | 7.10:1 |
| Gradient norm and GPU memory | `#455c63` / `#fff` | 7.08:1 |
| Secondary validation loss | `#16416a` / `#fff` | 10.51:1 |
| Lowest hero line contrast across a grid rule | `#006e86` / `#c9d6d5` | 3.93:1 |
| Stopped runs, login, registration, contact and notification errors | `#b21f2d` / `#fcebed` | 5.83:1 |
| Inline account validation on white | `#b21f2d` / `#fff` | 6.72:1 |
| Running status and success messages | `#216449` / `#e7f3ed` | 6.18:1 |
| Done status | `#16416a` / `#e7f1f7` | 9.17:1 |
| Information notifications | `#20598b` / `#e7f1f7` | 6.40:1 |
| Warning notifications | `#a3245a` / `#f8faf8` | 6.77:1 |
| Install field text | `#172a32` / `#e7f1f7` | 12.96:1 |
| Steps field text | `#172a32` / `#e7f3ed` | 13.04:1 |
| Body text on paper | `#172a32` / `#f8faf8` | 14.16:1 |
| Secondary text on paper | `#455c63` / `#f8faf8` | 6.75:1 |
| Pitch text and footer links | `#e5f1f0` / `#152c33` | 12.62:1 |
| Footer headings and solid fallback | `#bad1d1` / `#152c33` | 9.12:1 |
| Closing band text | `#fff` / `#184c4a` | 9.67:1 |
| Form control border on white | `#71898c` / `#fff` | 3.71:1 |

The retired-name search returned zero matches across `frontend/src` on both heads. The public stylesheets contained no saturated hex value between 10° and 60°. The signed-in notification stylesheet matches the previous head byte for byte.

### Paint inside the letters

These are solid interior pixels sampled in native WebKit. The footer is `#152c33`. A white plotting surface and a light grid remain visible behind each trace. Heatmap cells use their original intensities.

| Paint | Rendered color | Against footer | Against plotting surface |
|---|---|---:|---:|
| Loss line | `#638bae` | 4.05:1 | 3.60:1 |
| Second loss line | `#5c7a97` | 3.25:1 | 4.48:1 |
| Accuracy line | `#649380` | 4.19:1 | 3.48:1 |
| Densest heatmap cell | `#518d89` | 3.83:1 | 3.80:1 |
| Digit tile behind a white digit | `#bb5d85` | 3.48:1 | 4.19:1 |
| White field and digit ink | `#ffffff` | 14.58:1 |   |

The lowest footer trace-to-grid contrast was 3.04:1. The solid fallback is 9.12:1 against the footer.

## Screen checks

These measurements cover both PR heads. Each width was checked in Chromium and native macOS WebKit. The last row uses real browser page zoom.

| Viewport | Footer width in CSS pixels | Six letters, no horizontal overflow | Clipped plots and flat fallback |
|---|---:|---|---|
| 320 × 568 | 288 | Pass | Pass |
| 390 × 844 | 351 | Pass | Pass |
| 768 × 1024 | 691.219 | Pass | Pass |
| 1440 × 900 | 1296 | Pass | Pass |
| 1920 × 1080 | 1744 | Pass | Pass |
| 2560 × 1440 | 2384 | Pass | Pass |
| 3440 × 1440 | 3264 | Pass | Pass |
| 1440 × 900 at 200% | 648 | Pass | Pass |

Both engines checked all nine requested routes at 25 viewport sizes, signed in and signed out, under both motion preferences. Each engine also checked the nine routes at 200% on a 1440 × 900 window, yielding a 720 × 450 CSS viewport. That gives 936 checks per branch per engine. The three service routes on the start-only branch correctly reached its public 404.

The signed-in root still returns the existing dashboard. It retains 11 controls below 44px and 12px text, plus horizontal overflow on the six portrait phones through 430px.

Native WebKit exposed one image named “visdom” and ignored the artwork. The SVG had no focus targets or animations. Normal and reduced-motion snapshots matched byte for byte. Disabling the enhancement in the stylesheet restored the solid letters. Pixel comparisons found data in every letter with no clipping outside the silhouette beyond antialiasing.

Login, registration, password recovery and Contact errors were exercised with local fixtures. Contact checks covered missing and invalid fields, a server field error, a rate-limit response, a server failure and a successful retry with the message preserved.

Lint and the production builds passed on both branches. The focused tests passed, 14 on the start branch and 18 on the integrated branch. Mobile Lighthouse measured 86 performance and 100 accessibility on the start branch, and 84 performance and 100 accessibility on the integrated branch.

Firefox was unavailable. Physical devices, screen-reader speech and production traffic were outside this check. The fallback was exercised by disabling the real enhancement rule in a current WebKit engine.
