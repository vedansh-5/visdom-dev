/* Copyright 2017-present, The Visdom Authors */
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../../context/AuthContext';
import Contact from '../Contact';

vi.mock('../../context/AuthContext', () => ({ api: { post: vi.fn() } }));

function show(path = '/contact') {
  render(<MemoryRouter initialEntries={[path]}><Contact /></MemoryRouter>);
  return userEvent.setup();
}

async function fill(user) {
  await user.type(screen.getByLabelText('Name'), 'Ana');
  await user.type(screen.getByLabelText('Email'), 'ana@fossasia.org');
  await user.type(screen.getByLabelText('Message'), 'Can you help with a workspace?');
}

describe('Contact', () => {
  beforeEach(() => { api.post.mockReset(); });

  it('helps visitors describe a problem and explains when messages are reviewed', () => {
    show();
    expect(screen.getByRole('heading', { name: 'What to include' })).toBeVisible();
    expect(screen.getByText(/error message/)).toBeVisible();
    expect(screen.getByRole('heading', { name: 'When to expect a reply' })).toBeVisible();
    expect(screen.getByText(/allow a few days for a reply.*spare time.*take longer/i)).toBeVisible();
  });

  it('describes each invalid field and focuses the first one', async () => {
    const user = show();
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    expect(screen.getByLabelText('Name')).toHaveFocus();
    expect(screen.getByLabelText('Name')).toHaveAccessibleDescription('Enter your name.');
    expect(screen.getByLabelText('Email')).toHaveAccessibleDescription('Enter your email address.');
    expect(screen.getByLabelText('Message')).toHaveAccessibleDescription('Enter a message.');
    await user.type(screen.getByLabelText('Email'), 'ana');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    expect(screen.getByLabelText('Email')).toHaveAccessibleDescription('Enter a valid email address.');
    expect(api.post).not.toHaveBeenCalled();
  });

  it('sends once, announces progress and confirms receipt', async () => {
    let finish;
    api.post.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const user = show('/contact?topic=Billing');
    expect(screen.getByLabelText('Topic')).toHaveValue('Billing');
    await fill(user);
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    expect(screen.getByRole('button', { name: 'Sending…' })).toBeDisabled();
    expect(api.post).toHaveBeenCalledWith('/contact', {
      name: 'Ana', email: 'ana@fossasia.org', topic: 'Billing', message: 'Can you help with a workspace?', website: '',
    });
    await act(async () => finish({ status: 204 }));
    expect(screen.getByRole('status')).toHaveTextContent('Message sent');
  });

  it('keeps the message for a retry after an error', async () => {
    api.post.mockRejectedValueOnce(new Error('unavailable')).mockResolvedValueOnce({ status: 204 });
    const user = show('/contact?topic=unknown');
    expect(screen.getByLabelText('Topic')).toHaveValue('General');
    await fill(user);
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('try again later');
    expect(screen.getByLabelText('Message')).toHaveValue('Can you help with a workspace?');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    expect(await screen.findByText('Message sent')).toBeVisible();
  });
});
