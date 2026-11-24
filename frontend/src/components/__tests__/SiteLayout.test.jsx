/* Copyright 2017-present, The Visdom Authors */
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it } from 'vitest';
import SiteLayout from '../SiteLayout';

function mount() {
  render(<MemoryRouter><SiteLayout><main>Page</main></SiteLayout></MemoryRouter>);
}

it('links home from the header and groups public destinations in the footer', () => {
  mount();
  expect(within(screen.getByRole('banner')).getByRole('link', { name: 'Visdom home' })).toHaveAttribute('href', '/');
  const footer = within(screen.getByRole('contentinfo'));
  for (const [name, path] of [['Pricing', '/pricing'], ['Terms', '/terms'], ['Contact us', '/contact']]) {
    expect(footer.getByRole('link', { name })).toHaveAttribute('href', path);
  }
  expect(footer.getByText('visdom.dev is run by FOSSASIA PTE. LTD., Singapore.')).toBeVisible();
});

it('cycles focus inside the mobile menu and returns focus after dismissal', async () => {
  mount();
  const user = userEvent.setup();
  const trigger = screen.getByRole('button', { name: 'Menu' });
  const panel = document.querySelector('dialog');
  panel.showModal = () => { panel.open = true; };
  panel.close = () => {
    panel.open = false;
    panel.dispatchEvent(new Event('close'));
  };
  await user.click(trigger);
  const dialog = screen.getByRole('dialog');
  const close = within(dialog).getByRole('button', { name: 'Close menu' });
  close.focus();
  await user.tab({ shift: true });
  expect(within(dialog).getByRole('link', { name: 'Get started' })).toHaveFocus();
  await user.tab();
  expect(close).toHaveFocus();
  await user.click(close);
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(trigger).toHaveFocus();
});
