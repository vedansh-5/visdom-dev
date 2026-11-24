/* Copyright 2017-present, The Visdom Authors */

import { useSyncExternalStore } from 'react';
import { Link } from 'react-router-dom';
import Chart from './Chart';
import '../../css/start-hero.css';
import { BLUE, CHARTS, LIVE_POINTS, LIVE_TARGET } from './chartData';

const PANES = [
  ['Training loss', 'live'], ['Sample batch', 'digits'], ['Validation accuracy', 'acc'],
  ['Confusion matrix', 'heat'], ['Learning rate', 'lr'], ['Validation loss', 'loss2'],
  ['Gradient norm', 'grad'], ['Validation batch', 'digits'], ['GPU memory, GB', 'gpu'],
  ['Top-5 accuracy', 'acc2'], ['Attention weights', 'heat'], ['Training loss · ViT', 'loss3'],
  ['Augmented batch', 'digits'], ['Validation accuracy · ViT', 'acc3'], ['Learning rate · ViT', 'lr'],
  ['Class predictions', 'heat'], ['Validation loss · ViT', 'loss4'], ['Training batch · ViT', 'digits'],
  ['Accuracy · ConvNeXt', 'acc2'], ['Gradient norm · ViT', 'grad'], ['Validation batch · ViT', 'digits'],
  ['Class attention', 'heat'], ['Loss · ConvNeXt', 'loss2'], ['Learning rate · ConvNeXt', 'lr'],
  ['Validation samples', 'digits'], ['Accuracy · ResNet', 'acc'],
];

const columnBreakpoints = [[2560, 10], [1920, 8], [1680, 7], [1280, 6], [1024, 5], [768, 4], [480, 3], [0, 2]];
const screenColumns = () => columnBreakpoints.find(([minWidth]) => window.innerWidth >= minWidth)[1];
const screenMode = () => {
  if (window.innerWidth < 480 && window.innerHeight >= 275 && window.innerHeight <= 460) return 'compact';
  if (window.innerHeight <= 345) return 'shallow';
  return window.innerHeight <= 620 ? 'short' : 'regular';
};
const onResize = notify => {
  window.addEventListener('resize', notify);
  return () => window.removeEventListener('resize', notify);
};

const DIGITS = [
  'M12 5C4 6 3 22 11 22S22 5 15 5Z', 'M7 10l7-5-2 17',
  'M5 10Q10 0 17 7Q21 12 6 21l14-1', 'M6 6Q21 1 16 11l-5 1q15-3 6 8-5 5-12-1',
  'M15 4L5 15h15m-4-9-2 17', 'M19 5H9l-3 9q11-7 12 1 0 10-13 5',
  'M17 4Q5 8 6 18c1 8 13 4 12-2q-2-7-12-1', 'M5 6h15L9 22',
  'M12 12C-1 7 18-2 18 7s-16 9-11 14 20-1 5-9Z', 'M17 12C5 18 3 7 12 5s9 5 0 17',
];

const Samples = ({ seed }) => (
  <div className="st-samples" role="img" aria-label="A training batch of handwritten digits">
    {Array.from({ length: 6 }, (_, i) => (
      <svg key={i} viewBox="0 0 26 27" aria-hidden="true">
        <path d={DIGITS[(seed + i * 3) % DIGITS.length]} fill="none" stroke="currentColor"
          strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" transform={`rotate(${(seed + i) % 5 * 4 - 8} 13 13)`} />
      </svg>
    ))}
  </div>
);

const Heat = ({ seed }) => (
  <div className="st-heat" role="img" aria-label="Heatmap of class scores">
    {Array.from({ length: 64 }, (_, i) => {
      const intensity = i % 9 === 0 ? 0.9 : Math.abs(Math.sin(i * 7.3 + seed)) * 0.48;
      return <i key={i} style={{ opacity: intensity + 0.08 }} />;
    })}
  </div>
);

export default function StartHero({ boardRef, count }) {
  const columns = useSyncExternalStore(onResize, screenColumns);
  const mode = useSyncExternalStore(onResize, screenMode);
  const compact = mode === 'compact';
  const shallow = mode === 'shallow';
  const rowCount = shallow ? 1 : compact ? 2 : 3;
  const span = columns >= 8 || (shallow && columns === 6) ? 4
    : columns === 3 && mode !== 'regular' ? 2 : 2 + columns % 2;
  const pitchRows = mode === 'short' && columns > 2 ? 3 : 1;
  const pitchStart = pitchRows === 3 || compact || shallow ? 1 : 2;
  const live = [{ y: LIVE_TARGET.slice(0, count), c: BLUE }];
  return (
    <section className={`st-sheet st-sheet-${mode}`} ref={boardRef} aria-label="Experiment previews" style={{
      gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
    }}>
      <div className="st-pitch" style={{
        gridColumn: `${1 + Math.floor((columns - span) / 2)} / span ${span}`,
        gridRow: `${pitchStart} / span ${pitchRows}`,
      }}>
        <span className="st-mark"><img src="/logo.svg" alt="" />visdom</span>
        <h1>Watch training live, together.</h1>
        <p>{compact || shallow ? 'Live plots, images and text for your team.' :
          'Your plots, images and text in the browser while training runs. Hosted for your team, no server to set up.'}</p>
        <div className="st-pitch-actions">
          <Link to="/register" className="st-btn">Get started</Link>
          <Link to="/login">Sign in</Link>
        </div>
      </div>
      {PANES.slice(0, columns * rowCount - pitchRows * span).map(([title, type], i) => (
        <div key={title} className={`st-pane st-tone-${i % 4}`}>
          <div className="st-pane-strip">{title}</div>
          <div className="st-pane-body">
            {type === 'digits' ? <Samples seed={i} /> : type === 'heat' ? <Heat seed={i} /> : (
              <Chart label={title} lines={type === 'live' ? live : CHARTS[type]}
                slots={type === 'live' ? LIVE_POINTS : undefined} range={type === 'live' ? LIVE_TARGET : undefined} />
            )}
            {type === 'live' && <span className="st-live">Live · step {(count * 500).toLocaleString('en-US')}</span>}
          </div>
        </div>
      ))}
    </section>
  );
}
