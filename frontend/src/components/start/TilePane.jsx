/* Copyright 2017-present, The Visdom Authors */

import { memo, useMemo, useRef, useState } from 'react';

const DIGITS = [
  'M12 5C4 6 3 22 11 22S22 5 15 5Z', 'M7 10l7-5-2 17',
  'M5 10Q10 0 17 7Q21 12 6 21l14-1', 'M6 6Q21 1 16 11l-5 1q15-3 6 8-5 5-12-1',
  'M15 4L5 15h15m-4-9-2 17', 'M19 5H9l-3 9q11-7 12 1 0 10-13 5',
  'M17 4Q5 8 6 18c1 8 13 4 12-2q-2-7-12-1', 'M5 6h15L9 22',
  'M12 12C-1 7 18-2 18 7s-16 9-11 14 20-1 5-9Z', 'M17 12C5 18 3 7 12 5s9 5 0 17',
];

const heatCells = (title, seed) => Array.from({ length: 64 }, (_, i) => {
  const row = Math.floor(i / 8);
  const col = i % 8;
  const value = (0.08 + (row === col ? 0.9 : Math.abs(Math.sin(i * 7.3 + seed)) * 0.48)).toFixed(2);
  let axes = `query token ${row} · key token ${col}`;
  if (title === 'Confusion matrix') axes = `true ${row} · predicted ${col}`;
  if (title === 'Class predictions') axes = `class ${row} · predicted ${col}`;
  return { colour: `rgba(24, 88, 148, ${value})`, readout: `${axes} · ${value}` };
});

const digitCells = seed => Array.from({ length: 6 }, (_, i) => {
  const digit = (seed + i * 3) % DIGITS.length;
  const wrong = (seed + i) % 6 === 0;
  const prediction = wrong ? (digit + 1) % DIGITS.length : digit;
  const score = (wrong ? 0.64 + i / 100 : 0.91 + (seed + i) % 9 / 100).toFixed(2);
  return { path: DIGITS[digit], readout: `label ${digit} · pred ${prediction} · ${score}` };
});

const TilePane = memo(function TilePane({ type, title, seed }) {
  const samples = type === 'digits';
  const columns = samples ? 3 : 8;
  const cells = useMemo(() => samples ? digitCells(seed) : heatCells(title, seed), [samples, title, seed]);
  const [selected, setSelected] = useState(null);
  const touchSelection = useRef(false);
  const index = selected ?? 0;
  const last = cells.length - 1;

  const inspect = event => {
    const tile = event.target.closest('[data-tile]');
    if (tile) {
      setSelected(Number(tile.dataset.tile));
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const rows = cells.length / columns;
    const col = Math.max(0, Math.min(columns - 1, Math.floor((event.clientX - rect.left) / rect.width * columns)));
    const row = Math.max(0, Math.min(rows - 1, Math.floor((event.clientY - rect.top) / rect.height * rows)));
    setSelected(row * columns + col);
  };

  const keyDown = event => {
    const col = index % columns;
    const next = {
      ArrowLeft: col > 0 ? index - 1 : index, ArrowRight: col < columns - 1 ? index + 1 : index,
      ArrowUp: index >= columns ? index - columns : index, ArrowDown: index + columns <= last ? index + columns : index,
      Home: 0, End: last, Enter: index, ' ': index,
    }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    touchSelection.current = false;
    setSelected(next);
  };

  return (
    <div className={samples ? 'st-samples' : 'st-heat'} role="slider" tabIndex={0} aria-label={title}
      aria-valuemin={1} aria-valuemax={cells.length} aria-valuenow={index + 1} aria-valuetext={cells[index].readout}
      onPointerDown={event => {
        event.currentTarget.focus({ preventScroll: true });
        touchSelection.current = event.pointerType === 'touch';
        inspect(event);
      }}
      onPointerMove={event => {
        if (event.pointerType === 'touch' || event.nativeEvent.sourceCapabilities?.firesTouchEvents) return;
        touchSelection.current = false;
        inspect(event);
      }}
      onPointerLeave={event => { if (event.pointerType !== 'touch' && !touchSelection.current) setSelected(null); }}
      onFocus={() => setSelected(current => current ?? 0)}
      onBlur={() => { touchSelection.current = false; setSelected(null); }} onKeyDown={keyDown}>
      {cells.map((cell, i) => {
        const props = { 'data-tile': i, 'aria-hidden': true, className: selected === i ? 'st-selected-tile' : undefined };
        return samples ? (
          <svg key={i} {...props} viewBox="0 0 26 27">
            <path d={cell.path} fill="none" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round"
              strokeLinejoin="round" transform={`rotate(${(seed + i) % 5 * 4 - 8} 13 13)`} />
          </svg>
        ) : <i key={i} {...props} style={{ backgroundColor: cell.colour }} />;
      })}
      {selected !== null && <span className="st-readout" aria-hidden="true"
        style={index >= cells.length / 2 ? { top: 4, bottom: 'auto' } : undefined}>{cells[selected].readout}</span>}
    </div>
  );
});

export default TilePane;
