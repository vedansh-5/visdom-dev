/* Copyright 2017-present, The Visdom Authors */

import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import Start from '../Start';

const renderStart = () => render(<MemoryRouter><Start /></MemoryRouter>);
const board = () => screen.getByRole('region', { name: 'Experiment previews' });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it('fills the available grid as the screen changes size', () => {
  renderStart();
  for (const [width, columns, span] of [[360, 2, 2], [550, 3, 3], [844, 4, 2], [1024, 5, 3], [1280, 6, 2], [1700, 7, 3], [2000, 8, 4], [2560, 10, 4]]) {
    vi.stubGlobal('innerWidth', width);
    fireEvent(window, new Event('resize'));
    expect(board().querySelectorAll('.st-pane')).toHaveLength(columns * 3 - span);
    expect(within(board()).getByRole('heading', { level: 1 })).toBeVisible();
  }
  vi.stubGlobal('innerWidth', 844);
  vi.stubGlobal('innerHeight', 390);
  fireEvent(window, new Event('resize'));
  expect(board().querySelectorAll('.st-pane')).toHaveLength(6);
});

it.each([[375, 320, 'compact', 2], [1280, 240, 'shallow', 2]])(
  'uses complete pane rows on a %i by %i screen', (width, height, mode, panes) => {
    vi.stubGlobal('innerWidth', width);
    vi.stubGlobal('innerHeight', height);
    renderStart();
    expect(board()).toHaveClass(`st-sheet-${mode}`);
    expect(board().querySelectorAll('.st-pane')).toHaveLength(panes);
    expect(within(board()).getByRole('slider', { name: 'Training loss' })).toBeVisible();
  }
);

it('reads a chart point with a pointer or keyboard', () => {
  renderStart();
  const chart = within(board()).getAllByRole('slider')[0];
  vi.spyOn(chart, 'getBoundingClientRect').mockReturnValue({ left: 0, width: 200 });
  fireEvent.pointerDown(chart, { clientX: 0, pointerType: 'touch' });
  expect(chart).toHaveAttribute('aria-valuenow', '1');
  fireEvent.keyDown(chart, { key: 'ArrowRight' });
  expect(chart).toHaveAttribute('aria-valuenow', '2');
  expect(chart).toHaveAttribute('aria-valuetext', expect.stringMatching(/Point 2/));
});

it('ticks only while the board is visible and motion is enabled', () => {
  vi.useFakeTimers();
  let shown;
  vi.stubGlobal('IntersectionObserver', class {
    constructor(callback) { this.callback = callback; }
    observe(element) {
      if (element.getAttribute('aria-label') === 'Experiment previews') {
        shown = (isIntersecting) => this.callback([{ target: element, isIntersecting }]);
      }
    }
    disconnect() {}
    unobserve() {}
  });
  const motion = new EventTarget();
  motion.matches = false;
  vi.stubGlobal('matchMedia', () => motion);
  renderStart();
  const step = () => within(board()).getByText(/step [\d,]+/i).textContent;
  const tick = () => act(() => vi.advanceTimersByTime(700));
  const first = step();
  tick();
  expect(step()).toBe(first);
  act(() => shown(true));
  tick();
  expect(step()).not.toBe(first);
  const second = step();
  act(() => shown(false));
  tick();
  expect(step()).toBe(second);
  const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  act(() => shown(true));
  fireEvent(document, new Event('visibilitychange'));
  tick();
  expect(step()).toBe(second);
  hidden.mockReturnValue(false);
  motion.matches = true;
  fireEvent(document, new Event('visibilitychange'));
  tick();
  expect(step()).toBe(second);
  motion.matches = false;
  fireEvent(motion, new Event('change'));
  tick();
  expect(step()).not.toBe(second);
});
