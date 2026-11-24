/* Copyright 2017-present, The Visdom Authors */
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../context/AuthContext';
import usePageTitle from '../hooks/usePageTitle';
import '../css/contact.css';

const TOPICS = ['General', 'Billing', 'Account', 'Security', 'Other'];

function validate(values, form) {
  const errors = {};
  if (!values.name) errors.name = 'Enter your name.';
  if (values.name.length > 100) errors.name = 'Use 100 characters or fewer.';
  if (!values.email) errors.email = 'Enter your email address.';
  else if (form.elements.email.validity.typeMismatch || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email)) {
    errors.email = 'Enter a valid email address.';
  }
  if (values.email.length > 254) errors.email = 'Use 254 characters or fewer.';
  if (!TOPICS.includes(values.topic)) errors.topic = 'Choose a topic.';
  if (!values.message) errors.message = 'Enter a message.';
  if (values.message.length > 5000) errors.message = 'Use 5,000 characters or fewer.';
  return errors;
}

function ContactField({ label, name, error, children }) {
  return (
    <div className="contact-field">
      <label htmlFor={`contact-${name}`}>{label}</label>
      {children}
      {error && <span className="contact-error" id={`contact-${name}-error`}>{error}</span>}
    </div>
  );
}

export default function Contact() {
  usePageTitle('Contact');
  const [params] = useSearchParams();
  const initialTopic = TOPICS.find(topic => topic.toLowerCase() === params.get('topic')?.toLowerCase()) || 'General';
  const [state, setState] = useState('idle');
  const [errors, setErrors] = useState({});
  const busy = state === 'sending';

  function field(name) {
    return {
      id: `contact-${name}`, name, required: true,
      'aria-invalid': errors[name] ? true : undefined,
      'aria-describedby': errors[name] ? `contact-${name}-error` : undefined,
    };
  }

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const values = Object.fromEntries(Array.from(new FormData(form), ([key, value]) => [key, value.trim()]));
    const invalid = validate(values, form);
    setErrors(invalid);
    const first = Object.keys(invalid)[0];
    if (first) {
      setState('idle');
      form.elements[first].focus();
      return;
    }
    setState('sending');
    try {
      await api.post('/contact', values);
      setState('sent');
    } catch (error) {
      if (error.response?.status === 422) {
        const fields = error.response.data?.detail;
        const emailInvalid = Array.isArray(fields) && fields.some(issue => issue.loc?.at(-1) === 'email');
        if (emailInvalid) {
          setErrors({ email: 'Enter a valid email address.' });
          setState('idle');
          requestAnimationFrame(() => form.elements.email.focus());
          return;
        }
      }
      setState('failed');
    }
  }

  return (
    <main className="contact-page">
      <div className="contact-layout">
        <header className="contact-intro">
          <h1>Contact us</h1>
          <p>Send a question or report a problem to the team that runs visdom.dev.</p>
          <Link to="/privacy">How we use your information</Link>
        </header>
        {state === 'sent' ? (
          <div role="status" className="contact-panel">
            <h2 tabIndex={-1} ref={node => node?.focus()}>Message sent</h2>
            <p>The visdom.dev team has received your message.</p>
            <Link to="/">Back to home</Link>
          </div>
        ) : (
          <form className="contact-panel" onSubmit={submit} noValidate>
            <fieldset disabled={busy}>
              <legend>Your message</legend>
              <div className="contact-pair">
                <ContactField name="name" label="Name" error={errors.name}>
                  <input {...field('name')} autoComplete="name" maxLength={100} />
                </ContactField>
                <ContactField name="email" label="Email" error={errors.email}>
                  <input {...field('email')} type="email" autoComplete="email" maxLength={254} />
                </ContactField>
              </div>
              <ContactField name="topic" label="Topic" error={errors.topic}>
                <select {...field('topic')} defaultValue={initialTopic}>
                  {TOPICS.map(topic => <option key={topic}>{topic}</option>)}
                </select>
              </ContactField>
              <ContactField name="message" label="Message" error={errors.message}>
                <textarea {...field('message')} rows={5} maxLength={5000} />
              </ContactField>
              <div hidden>
                <label htmlFor="contact-website">Website</label>
                <input id="contact-website" name="website" tabIndex={-1} autoComplete="off" maxLength={200} />
              </div>
              {state === 'failed' && <p role="alert" className="contact-error">We couldn’t send your message. Please try again later.</p>}
              <button type="submit" disabled={busy}>{busy ? 'Sending…' : 'Send message'}</button>
              <span role="status" className="contact-sr">{busy ? 'Sending your message.' : ''}</span>
            </fieldset>
          </form>
        )}
        <aside className="contact-guide" aria-label="Writing to the team">
          <h2>What to include</h2>
          <p>For a billing question, tell us which plan or charge you mean. For a problem with a workspace, include its name, what you tried and any error message. Keep passwords and API keys private.</p>
          <h2>When to expect a reply</h2>
          <p>Please allow a few days for a reply. Contributors review messages in their spare time, so it can take longer.</p>
        </aside>
      </div>
    </main>
  );
}
