/* Copyright 2017-present, The Visdom Authors */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, useAuth } from '../context/AuthContext';
import usePageTitle from '../hooks/usePageTitle';
import { planAction } from '../utils/billing';
import { cachedGet } from '../utils/requestCache';
import '../css/pricing.css';

const storage = (mb) => mb >= 1024 && mb % 1024 === 0
  ? `${(mb / 1024).toLocaleString()} GB`
  : `${mb.toLocaleString()} MB`;

const LIMITS = [
  { label: 'Workspaces', key: 'workspaces' },
  { label: 'Members', key: 'members' },
  { label: 'API keys', key: 'api_keys' },
  { label: 'Storage', key: 'storage_mb', format: storage },
  { label: 'Storage per workspace', key: 'workspace_storage_mb', format: storage },
  { label: 'Retention', key: 'retention_days', format: (days) => `${days} ${days === 1 ? 'day' : 'days'}` },
];

function limitValue(plan, { key, format }) {
  const value = key === 'retention_days' ? plan.retention_days : plan.limits[key];
  if (value === null) return 'Unlimited';
  return format ? format(value) : value.toLocaleString();
}

function ComparePlans({ plans }) {
  return (
    <section className="pricing-section" aria-labelledby="compare-title">
      <h2 id="compare-title">Compare plans</h2>
      <div className="pricing-table-wrap">
        <table aria-labelledby="compare-title">
          <thead>
            <tr>
              <th scope="col">Plan limits</th>
              {plans.map((plan) => <th scope="col" key={plan.id}>{plan.name}</th>)}
            </tr>
          </thead>
          <tbody>
            {LIMITS.map((limit) => (
              <tr key={limit.key}>
                <th scope="row">{limit.label}</th>
                {plans.map((plan) => <td key={plan.id}>{limitValue(plan, limit)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pricing-mobile-limits">
        {plans.map((plan) => (
          <section key={plan.id}>
            <h3>{plan.name}</h3>
            <dl>
              {LIMITS.map((limit) => (
                <div key={limit.key}>
                  <dt>{limit.label}</dt><dd>{limitValue(plan, limit)}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </section>
  );
}

function PlanCard({ plan, user, sessionLoading }) {
  const custom = plan.price === null;
  const action = custom && planAction(plan, {});
  let label = custom ? action.label : `Choose ${plan.name}`;
  let path = custom ? '/contact?topic=Billing' : `/register?plan=${encodeURIComponent(plan.id)}`;
  if (user) {
    label = 'Open billing';
    path = '/?tab=billing';
  }
  return (
    <article className="pricing-card" aria-labelledby={`offer-${plan.id}`}>
      <h2 id={`offer-${plan.id}`}>{plan.name}</h2>
      <p className="pricing-price">
        {custom ? action.label : plan.price === 0 ? 'Free' : <><span>${plan.price}</span> <small>/ month</small></>}
      </p>
      <ul>
        {plan.features.map((feature) => <li key={feature}>{feature}</li>)}
      </ul>
      {sessionLoading
        ? <span className="pricing-session">Checking session…</span>
        : <Link className="pricing-action" to={path}>{label}</Link>}
    </article>
  );
}

function PricingFaq() {
  return (
    <section className="pricing-section pricing-faq" aria-labelledby="faq-title">
      <h2 id="faq-title">Frequently asked questions</h2>
      <div>
        <details>
          <summary>What counts toward storage?</summary>
          <p>Storage is the disk space used by the workspaces you own, including their plots, values and text. Workspaces in the trash count until their files are removed.</p>
        </details>
        <details>
          <summary>What happens after the retention period?</summary>
          <p>The clock starts when an environment was last written to. After the retention period for its owner’s plan, the service may remove that environment and its plots.</p>
        </details>
        <details>
          <summary>How do I cancel a paid plan?</summary>
          <p>Open the Billing tab in your dashboard and choose Manage billing. You can stop renewal in the Stripe customer portal and see when your plan ends in the dashboard.</p>
        </details>
        <details>
          <summary>Who handles payments?</summary>
          <p>Stripe processes payments for paid plans. Your payment details go directly to Stripe. Visdom keeps a record of your subscription and renewal date.</p>
        </details>
        <details>
          <summary>Can I host Visdom myself?</summary>
          <p>Yes. You can run the open-source Visdom server on your own machine. The installation instructions are in the <a href="https://github.com/fossasia/visdom">Visdom repository</a>.</p>
        </details>
      </div>
    </section>
  );
}

export default function Pricing() {
  usePageTitle('Pricing');
  const { user, loading } = useAuth();
  const [plans, setPlans] = useState(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    cachedGet('/billing/plans', () => api.get('/billing/plans').then((res) => res.data))
      .then((data) => { if (active) setPlans(data); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [attempt]);

  const retry = () => {
    setFailed(false);
    setAttempt((current) => current + 1);
  };

  return (
    <main className="pricing-page">
      <div className="pricing-content">
        <header className="pricing-intro">
          <h1>Pricing</h1>
          <p>Compare workspace limits, storage and plot retention for hosted Visdom.</p>
        </header>
        {failed ? (
          <div className="pricing-notice">
            <p role="alert">We couldn’t load plans. Please try again.</p>
            <button type="button" className="pricing-action" onClick={retry}>Try again</button>
          </div>
        ) : plans === null ? (
          <p role="status" className="pricing-notice">Loading plans…</p>
        ) : plans.length === 0 ? (
          <p className="pricing-notice">There are no public plans available right now.</p>
        ) : (
          <>
            <div className="pricing-cards">
              {plans.map((plan) => <PlanCard key={plan.id} plan={plan} user={user} sessionLoading={loading} />)}
            </div>
            <ComparePlans plans={plans} />
          </>
        )}
        <PricingFaq />
      </div>
    </main>
  );
}
