/* Copyright 2017-present, The Visdom Authors */
import axios from 'axios';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api, AuthProvider, useAuth } from '../../context/AuthContext';
import { clearRequestCache } from '../../utils/requestCache';
import Register from '../Register';
import Pricing from '../Pricing';

const offers = [
  { id: 'team-research', name: 'Research', price: 29 },
  { id: 'pro', name: 'Pro', price: 20 },
  { id: 'starter', name: 'Starter', price: 0 },
].map(plan => ({
  ...plan, features: [], retention_days: 3,
  limits: { workspaces: 1, members: 2, api_keys: 1, storage_mb: 5, workspace_storage_mb: 5 },
}));

function Destination() {
  const { pathname, search } = useLocation();
  const { user } = useAuth();
  return <output aria-label="Destination">{user?.username} at {pathname}{search}</output>;
}

const register = vi.spyOn(axios, 'post');
const get = vi.spyOn(api, 'get');

beforeEach(() => {
  clearRequestCache();
  register.mockImplementation(async path => {
    if (path === '/api/v1/auth/refresh') throw new Error('Signed out');
    if (path === '/api/v1/auth/login') return { data: { access_token: 'test-token' } };
    if (path === '/api/v1/auth/register') return { data: {} };
    throw new Error(path);
  });
  vi.spyOn(axios, 'get').mockResolvedValue({ data: { id: 1, username: 'ana' } });
  get.mockImplementation(async path => {
    if (path === '/billing/plans') return { data: offers };
    if (path === '/auth/generate-username') return { data: { username: 'ana' } };
    throw new Error(path);
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

async function signUp(entry) {
  const user = userEvent.setup();
  render(<MemoryRouter initialEntries={[entry]}>
    <AuthProvider>
      <Routes>
        <Route path="/register" element={<Register />} />
        <Route path="/pricing" element={<Pricing />} />
        <Route path="*" element={<Destination />} />
      </Routes>
    </AuthProvider>
  </MemoryRouter>);
  if (entry === '/pricing') {
    await user.click(within(await screen.findByRole('article', { name: 'Research' })).getByRole('link'));
  }
  await screen.findByText('ana');
  await user.type(screen.getByLabelText('Email Address'), 'ana@fossasia.org');
  await user.type(screen.getByLabelText('Password', { exact: true }), 'example-password');
  await user.type(screen.getByLabelText('Confirm Password'), 'example-password');
  await user.click(screen.getByRole('button', { name: 'Create Account' }));
  const destination = await screen.findByLabelText('Destination');
  expect(register).toHaveBeenCalledWith('/api/v1/auth/register', {
    email: 'ana@fossasia.org', password: 'example-password', username: 'ana',
  });
  return destination.textContent;
}

it.each([
  ['/pricing', '/?tab=billing', 1],
  ['/register?plan=pro', '/?tab=billing', 1],
  ['/register?plan=team-research', '/?tab=billing', 1],
  ['/register?plan=starter', '/', 1],
  ['/register?plan=unknown', '/', 1],
  ['/register', '/', 0],
  ['/register?plan=team-research&next=%2Fshare%2Finvite', '/share/invite', 0],
  [{ pathname: '/register', search: '?plan=team-research', state: { from: '/share/invite' } }, '/share/invite', 0],
])('signs up from %j and opens %s', async (entry, expected, lookups) => {
  expect(await signUp(entry)).toBe(`ana at ${expected}`);
  expect(get.mock.calls.filter(([path]) => path === '/billing/plans')).toHaveLength(lookups);
});

it('still opens the dashboard when the chosen plan cannot be looked up', async () => {
  get.mockImplementation(async path => {
    if (path === '/billing/plans') throw new Error('Catalog unavailable');
    return { data: { username: 'ana' } };
  });
  expect(await signUp('/register?plan=team-research')).toBe('ana at /');
});
