/* Copyright 2017-present, The Visdom Authors */
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import App from '../../App';
import { CONTROLLER } from '../../content/legal';

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ user: null, loading: false }),
  api: { get: vi.fn(async () => ({ data: { username: 'ana' } })) },
}));

describe('Terms', () => {
  it('opens publicly and gives visitors a contact link in the terms', () => {
    window.history.replaceState({}, '', '/terms');
    render(<App />);
    const main = within(screen.getByRole('main'));
    const terms = within(main.getByRole('article'));
    expect(terms.queryByRole('link', { name: 'Back to sign in' })).toBeNull();
    expect(terms.getByRole('heading', { level: 1, name: /terms/i })).toBeVisible();
    expect(terms.getByText(CONTROLLER.name, { exact: false })).toBeVisible();
    expect(terms.getByRole('link', { name: 'Contact us' })).toHaveAttribute('href', '/contact');
    expect(terms.getByRole('heading', { name: /cancelling and refunds/i })).toBeVisible();
    expect(terms.getByText(/law of Singapore/i)).toBeVisible();
  });

  it('opens the terms from the links beside the registration form', async () => {
    window.history.replaceState({}, '', '/register?plan=group');
    render(<App />);
    await screen.findByText('ana');
    const panel = within(screen.getByRole('button', { name: 'Create Account' }).closest('.auth-panel'));
    const privacy = panel.getByRole('link', { name: 'Privacy' });
    const terms = within(privacy.parentElement).getByRole('link', { name: 'Terms' });
    await userEvent.click(terms);
    expect(window.location.pathname).toBe('/terms');
    expect(screen.getByRole('heading', { level: 1, name: /terms/i })).toBeVisible();
    const header = within(screen.getByRole('banner'));
    expect(header.getByRole('link', { name: 'Get started' })).toHaveAttribute('href', '/register?plan=group');
  });
});
