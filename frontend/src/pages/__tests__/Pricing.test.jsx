/* Copyright 2017-present, The Visdom Authors */
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api, useAuth } from '../../context/AuthContext';
import { clearRequestCache } from '../../utils/requestCache';
import Dashboard from '../Dashboard';
import Pricing from '../Pricing';

vi.mock('../../context/AuthContext', () => ({ api: { get: vi.fn() }, useAuth: vi.fn() }));

const limits = { workspaces: 2, members: 6, api_keys: 3, storage_mb: 2048, workspace_storage_mb: 512 };
const plans = [
  { id: 'solo', name: 'Solo', price: 0, features: ['Personal runs'], limits, retention_days: 1 },
  { id: 'group', name: 'Group', price: 37, features: ['Shared projects'], limits, retention_days: 14 },
  {
    id: 'lab', name: 'Lab', price: null, features: [], retention_days: null,
    limits: { workspaces: null, members: null, api_keys: null, storage_mb: null, workspace_storage_mb: null },
  },
];

function visit() {
  window.history.replaceState({}, '', '/pricing');
  render(
    <BrowserRouter>
      <Routes>
        <Route path="/pricing" element={<Pricing />} />
        <Route path="/" element={<Dashboard />} />
      </Routes>
    </BrowserRouter>,
  );
}

describe('Pricing', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    clearRequestCache();
    useAuth.mockReturnValue({ user: null, loading: false });
  });

  it('shows progress while fetching the public catalog', () => {
    api.get.mockReturnValue(new Promise(() => {}));
    visit();
    expect(screen.getByRole('status')).toHaveTextContent(/loading plans/i);
    expect(api.get).toHaveBeenCalledWith('/billing/plans');
  });

  it('shows a failure and can retry the request', async () => {
    api.get.mockRejectedValueOnce(new Error()).mockResolvedValueOnce({ data: plans });
    visit();
    expect(await screen.findByRole('alert')).toHaveTextContent(/load plans/i);
    await userEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByRole('article', { name: 'Solo' })).toBeInTheDocument();
  });

  it('keeps the selected plan for registration and directs custom requests to Billing', async () => {
    api.get.mockResolvedValue({ data: plans });
    visit();
    const solo = within(await screen.findByRole('article', { name: 'Solo' }));
    expect(solo.getByText('Free')).toBeVisible();
    expect(solo.getByRole('link')).toHaveAttribute('href', '/register?plan=solo');
    const group = within(screen.getByRole('article', { name: 'Group' }));
    expect(group.getByText('$37')).toBeVisible();
    expect(group.getByText('/ month')).toBeVisible();
    expect(group.getByText('Shared projects')).toBeVisible();
    expect(group.getByRole('link')).toHaveAttribute('href', '/register?plan=group');
    expect(within(screen.getByRole('article', { name: 'Lab' })).getByRole('link', { name: 'Contact us' }))
      .toHaveAttribute('href', '/contact?topic=Billing');
  });

  it('compares all limits from the API, including unlimited and single-day retention', async () => {
    api.get.mockResolvedValue({ data: plans });
    visit();
    const table = within(await screen.findByRole('table', { name: 'Compare plans' }));
    for (const [label, value] of [
      ['Workspaces', '2'], ['Members', '6'], ['API keys', '3'], ['Storage', '2 GB'],
      ['Storage per workspace', '512 MB'], ['Retention', '1 day'],
    ]) {
      const cells = within(table.getByRole('rowheader', { name: label }).closest('tr')).getAllByRole('cell');
      expect(cells[0]).toHaveTextContent(value);
      expect(cells[2]).toHaveTextContent('Unlimited');
    }
    expect(table.getByText('14 days')).toBeVisible();
  });

  it('waits for session discovery before showing account-specific links', async () => {
    api.get.mockResolvedValue({ data: plans });
    useAuth.mockReturnValue({ user: null, loading: true });
    visit();
    expect(within(await screen.findByRole('article', { name: 'Group' })).queryByRole('link')).toBeNull();
  });

  it('opens the dashboard Billing tab for signed-in visitors from every plan', async () => {
    useAuth.mockReturnValue({ user: { id: 42, tier: 'solo' }, loading: false });
    api.get.mockImplementation(async (path) => {
      if (path === '/billing/plans') return { data: plans };
      if (path === '/billing/subscription') return { data: { tier: 'solo' } };
      return { data: [] };
    });
    visit();
    const cards = await screen.findAllByRole('article');
    for (const card of cards) {
      expect(within(card).getByRole('link')).toHaveAttribute('href', '/?tab=billing');
    }
    await userEvent.click(within(cards[1]).getByRole('link'));
    expect(await screen.findByText('Subscription Plans')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Billing' })).toHaveClass('active');
  });
});
