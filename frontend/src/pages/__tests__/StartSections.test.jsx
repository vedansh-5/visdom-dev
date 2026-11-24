/* Copyright 2017-present, The Visdom Authors */

import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import Start from '../Start';
import { copyToClipboard } from '../../utils/clipboard';

vi.mock('../../utils/clipboard', () => ({ copyToClipboard: vi.fn() }));
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const visit = () => render(<MemoryRouter><Start /></MemoryRouter>);
const panel = name => within(screen.getByRole('region', { name }));

it('keeps all nine runs reachable and displays the selected run metrics and chart', () => {
  visit();
  const runs = panel('Every run, as it happens');
  const buttons = runs.getAllByRole('button');
  expect(buttons).toHaveLength(9);
  fireEvent.click(buttons[8]);
  const detail = panel('resnet18-baseline');
  expect(detail.getByText('90/90')).toBeVisible();
  expect(detail.getByText('0.402')).toBeVisible();
  expect(detail.getByText('Raj')).toBeVisible();
  expect(detail.getByText('Done')).toBeVisible();
  expect(detail.getByRole('slider')).toBeVisible();
  fireEvent.keyDown(buttons[8], { key: 'ArrowUp' });
  expect(buttons[7]).toHaveFocus();
  expect(buttons[7]).toHaveAttribute('aria-expanded', 'true');
  expect(runs.getAllByRole('button')).toHaveLength(9);
});

it('places the active chart beneath its row on small screens and alongside the list on desktop', () => {
  vi.stubGlobal('innerWidth', 390);
  visit();
  const runs = panel('Every run, as it happens');
  const last = runs.getAllByRole('button')[8];
  fireEvent.click(last);
  const detail = () => runs.getByRole('region', { name: 'resnet18-baseline' });
  expect(last.nextElementSibling).toBe(detail());
  vi.stubGlobal('innerWidth', 1024);
  fireEvent(window, new Event('resize'));
  expect(runs.getByRole('list').nextElementSibling).toBe(detail());
});

it('updates the live run and lets a visitor pause the separate plot demo', () => {
  vi.useFakeTimers();
  visit();
  const live = panel('resnet50-base').getByRole('slider');
  const demo = panel('Live plots, images and text');
  const chart = demo.getByRole('slider');
  const first = live.getAttribute('aria-valuemax');
  const sample = chart.getAttribute('aria-valuemax');
  fireEvent.click(demo.getByRole('button', { name: 'Pause' }));
  act(() => vi.advanceTimersByTime(700));
  expect(live).not.toHaveAttribute('aria-valuemax', first);
  expect(chart).toHaveAttribute('aria-valuemax', sample);
  fireEvent.click(demo.getByRole('button', { name: 'Resume' }));
  act(() => vi.advanceTimersByTime(700));
  expect(chart).not.toHaveAttribute('aria-valuemax', sample);
});

it('changes a role and supports undo for keys and join requests', () => {
  visit();
  const role = screen.getByRole('combobox', { name: 'Role for raj@fossasia.org' });
  fireEvent.change(role, { target: { value: 'Viewer' } });
  expect(role).toHaveValue('Viewer');
  const key = within(panel('Scoped API keys').getByText('lab-gpu-01').closest('li'));
  fireEvent.click(key.getByRole('button', { name: 'Revoke' }));
  expect(key.getByText('Revoked')).toBeVisible();
  fireEvent.click(key.getByRole('button', { name: 'Undo' }));
  expect(key.getByRole('button', { name: 'Revoke' })).toBeVisible();
  const request = within(screen.getByText('priya@fossasia.org').closest('li'));
  for (const [action, result] of [['Approve', 'Approved'], ['Decline', 'Declined']]) {
    fireEvent.click(request.getByRole('button', { name: action }));
    expect(request.getByText(result)).toBeVisible();
    fireEvent.click(request.getByRole('button', { name: 'Undo' }));
  }
});

it('sorts numeric trials in both directions and copies the displayed Python', async () => {
  visit();
  const sweeps = panel('Experiments and sweeps');
  const sort = sweeps.getByRole('button', { name: 'Accuracy' });
  fireEvent.click(sort);
  expect(sweeps.getAllByRole('row')[1]).toHaveTextContent('0.871');
  fireEvent.click(sort);
  expect(sweeps.getAllByRole('row')[1]).toHaveTextContent('0.902');
  expect(sort.closest('th')).toHaveAttribute('aria-sort', 'descending');
  const client = panel('The client you already use');
  copyToClipboard.mockResolvedValue(true);
  fireEvent.click(client.getByRole('button', { name: 'Copy' }));
  expect(copyToClipboard).toHaveBeenCalledWith(client.getByText(/vis.images\(batch/).textContent);
  expect(await client.findByText('Copied')).toBeVisible();
});
