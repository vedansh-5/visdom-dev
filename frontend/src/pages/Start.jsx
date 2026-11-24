/* Copyright 2017-present, The Visdom Authors */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import StartHero from '../components/start/StartHero';
import Chart from '../components/start/Chart';
import { BLUE, NAVY, CHARTS, LIVE_POINTS, LIVE_TARGET } from '../components/start/chartData';
import useLiveRun from '../components/start/useLiveRun';
import { CLIENT_INSTALL, plotSnippet } from '../utils/quickstart';

const GITHUB_VISDOM = 'https://github.com/fossasia/visdom';
const GITHUB_VISDOM_DEV = 'https://github.com/fossasia/visdom-dev';

const useReveal = (ref) => {
  useEffect(() => {
    const root = ref.current;
    if (!root) {
      return undefined;
    }
    const items = Array.from(root.querySelectorAll('.st-rise, .st-shutter'));
    if (!('IntersectionObserver' in window)) {
      items.forEach((el) => el.classList.add('st-in'));
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('st-in');
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15 }
    );
    items.forEach((el, i) => {
      el.style.transitionDelay = `${(i % 3) * 70}ms`;
      observer.observe(el);
    });
    return () => observer.disconnect();
  }, [ref]);
};

const RUNS = [
  { name: 'vit-small-patch16', epoch: '90/90', loss: '0.284', owner: 'Sam', status: 'Done' },
  { name: 'resnet50-aug-mixup', epoch: '63/90', loss: '0.361', owner: 'Raj', status: 'Running' },
  { name: 'resnet50-lr-3e-4', epoch: '12/90', loss: '1.902', owner: 'Ana', status: 'Stopped' },
  {
    name: 'resnet50-base',
    owner: 'Ana',
    status: 'Running',
    live: true,
    detail: 'Started 2 hours ago from lab-gpu-01. Four windows: loss, val accuracy, learning rate and a sample batch, updated every 500 steps.',
  },
  { name: 'efficientnet-b0', epoch: '90/90', loss: '0.297', owner: 'Raj', status: 'Done' },
  { name: 'optuna-trial-17', epoch: '20/20', loss: '0.455', owner: 'Sam', status: 'Done' },
  { name: 'optuna-trial-18', epoch: '7/20', loss: '0.731', owner: 'Sam', status: 'Running' },
  { name: 'convnext-tiny', epoch: '34/90', loss: '0.508', owner: 'Ana', status: 'Running' },
  { name: 'resnet18-baseline', epoch: '90/90', loss: '0.402', owner: 'Raj', status: 'Done' },
];

const STATUS_CLASS = { Running: 'st-s-run', Done: 'st-s-done', Stopped: 'st-s-stop' };

const RunsBoard = ({ liveEpoch, liveLoss }) => {
  const [open, setOpen] = useState(3);
  return (
    <ul className="st-runs" data-ui>
      {RUNS.map((run, i) => {
        const epoch = run.live ? `${liveEpoch}/90` : run.epoch;
        const loss = run.live ? liveLoss : run.loss;
        const detail = run.detail || `Epoch ${epoch}, loss ${loss}. Owned by ${run.owner}; its windows sit in the same workspace for everyone to open.`;
        return (
          <li key={run.name} className={`st-rise${open === i ? ' st-run-open' : ''}`}>
            <button type="button" aria-expanded={open === i} onClick={() => setOpen(i)}>
              <span>{run.name}</span>
              <span className="st-soft st-epoch">epoch {epoch}</span>
              <span className="st-soft st-loss">loss {loss}</span>
              <span className="st-soft st-owner">{run.owner}</span>
              <span className={`st-status ${STATUS_CLASS[run.status]}`}>{run.status}</span>
            </button>
            {open === i && <p className="st-detail">{detail}</p>}
          </li>
        );
      })}
    </ul>
  );
};

const FEATURES = [
  {
    title: 'Live plots, images and text',
    text: 'Line charts, scatter plots, heatmaps, images, audio and video, updated while the run is going.',
    fragment: (
      <div className="st-frag st-frag-shot" data-ui>
        <img src="/start/dashboard.png" alt="Loss, accuracy and learning rate plots in a Visdom environment" width="1400" height="967" loading="lazy" />
      </div>
    ),
  },
  {
    title: 'Workspaces and roles',
    text: 'One workspace per project. Admins manage it, members write to it, viewers only look.',
    fragment: (
      <div className="st-frag" data-ui>
        <table>
          <tbody>
            <tr><th>Member</th><th>Role</th></tr>
            <tr><td>ana@lab.org</td><td><span className="st-chip">Admin</span></td></tr>
            <tr><td>raj@lab.org</td><td><span className="st-chip">Member</span></td></tr>
            <tr><td>sam@lab.org</td><td><span className="st-chip">Viewer</span></td></tr>
          </tbody>
        </table>
      </div>
    ),
  },
  {
    title: 'Scoped API keys',
    text: 'Give each machine or pipeline its own key, set when it expires, and revoke it when you are done.',
    fragment: (
      <div className="st-frag" data-ui>
        <table>
          <tbody>
            <tr><th>Key</th><th>Reaches</th></tr>
            <tr><td>lab-gpu-01<br /><span className="st-chip">30 days left</span></td><td>resnet-sweeps</td></tr>
            <tr><td>ci-runner<br /><span className="st-chip">No expiry</span></td><td>All workspaces</td></tr>
          </tbody>
        </table>
      </div>
    ),
  },
  {
    title: 'Join links',
    text: 'Share one link to bring people in. Each person who opens it asks to join, and an admin approves them.',
    fragment: (
      <div className="st-frag" data-ui>
        {['priya@uni.edu', 'tom@lab.org', 'mei@uni.edu'].map((email) => (
          <div key={email} className="st-req">
            <span><b>{email}</b> asked to join resnet-sweeps</span>
            <span className="st-req-actions"><span className="st-mini">Approve</span><span className="st-mini st-mini-ghost">Decline</span></span>
          </div>
        ))}
      </div>
    ),
  },
  {
    title: 'Experiments and sweeps',
    text: 'Compare runs in the HParams dashboard, and log Optuna, PyTorch, Keras and XGBoost training as it happens.',
    fragment: (
      <div className="st-frag" data-ui>
        <table>
          <tbody>
            <tr><th>Trial</th><th>lr</th><th>batch</th><th>val acc</th></tr>
            <tr><td>15</td><td>1e-3</td><td>128</td><td>0.871</td></tr>
            <tr className="st-best"><td>17</td><td>3e-4</td><td>256</td><td>0.902</td></tr>
            <tr><td>16</td><td>1e-4</td><td>256</td><td>0.884</td></tr>
            <tr><td>18</td><td>3e-4</td><td>512</td><td>running</td></tr>
          </tbody>
        </table>
      </div>
    ),
  },
  {
    title: 'The client you already use',
    text: 'Keep your plotting code. Give the Visdom client a key and a workspace, and every call lands here.',
    fragment: (
      <div className="st-frag" data-ui>
        <pre className="st-code st-code-tall"><code>{`$ ${CLIENT_INSTALL}\n\nvis.line(Y=[loss], X=[step],\n         win="loss", update="append")\nvis.images(batch, win="samples")\nvis.text(notes, win="notes")`}</code></pre>
      </div>
    ),
  },
];

const Start = () => {
  const pageRef = useRef(null);
  useReveal(pageRef);
  const heroRef = useRef(null);
  const count = useLiveRun(heroRef);
  const snippet = useMemo(() => plotSnippet(), []);
  const liveEpoch = Math.min(90, Math.round((count / LIVE_POINTS) * 90));
  const liveLoss = Math.max(0.3, LIVE_TARGET[count - 1] / 4.3 + 0.2).toFixed(3);

  return (
    <div className="st-page" ref={pageRef}>
      <StartHero boardRef={heroRef} count={count} />

      <main>
        <section className="st-steps" aria-labelledby="st-how">
          <div className="st-field st-rise">
            <h2 id="st-how">From sign-up to first plot</h2>
            <div className="st-card" data-ui>
              <div className="st-row"><span className="st-big">resnet-sweeps</span><br /><span className="st-k">Workspace, created just now</span></div>
              <div className="st-row">1 member: you, admin</div>
            </div>
            <p className="st-clause">First you make a workspace.</p>
          </div>
          <div className="st-field st-rise">
            <div className="st-card" data-ui>
              <div className="st-row"><span className="st-big">lab-gpu-01</span><br /><span className="st-k">API key for resnet-sweeps</span></div>
              <div className="st-row">visdom_live_…3f9a<br /><span className="st-k">Expires in 30 days</span></div>
            </div>
            <p className="st-clause">Then you give your machine a key.</p>
          </div>
          <div className="st-field st-rise">
            <div className="st-card st-card-code" data-ui>
              <pre className="st-code"><code>{snippet}</code></pre>
            </div>
            <p className="st-clause">Then your script sends a plot.</p>
          </div>
          <div className="st-field st-rise">
            <div className="st-card" data-ui>
              <div className="st-row st-row-chart"><Chart lines={CHARTS.loss4} /></div>
              <div className="st-watchers">
                <i style={{ background: NAVY }}>A</i>
                <i style={{ background: BLUE }}>R</i>
                <i style={{ background: '#56688a' }}>S</i>
                <span className="st-k">watching</span>
              </div>
            </div>
            <p className="st-clause">And the whole team watches it grow.</p>
          </div>
        </section>

        <section className="st-board" aria-labelledby="st-runs">
          <h2 id="st-runs" className="st-rise">Every run, as it happens</h2>
          <RunsBoard liveEpoch={liveEpoch} liveLoss={liveLoss} />
        </section>

        <section className="st-features" aria-labelledby="st-get">
          <h2 id="st-get" className="st-rise">What you get</h2>
          <div className="st-cells">
            {FEATURES.map((feature) => (
              <div key={feature.title} className="st-cell st-rise">
                <div className="st-txt">
                  <h3>{feature.title}</h3>
                  <p>{feature.text}</p>
                </div>
                {feature.fragment}
              </div>
            ))}
          </div>
        </section>

        <section className="st-open" aria-labelledby="st-open-h">
          <figure className="st-open-pic st-rise">
            <img
              src="/start/fossasia-summit-2019.jpg"
              alt="Group photo of the FOSSASIA Summit 2019 at the Lifelong Learning Institute, Singapore"
              width="1600"
              height="737"
              loading="lazy"
            />
            <figcaption>FOSSASIA Summit 2019, Singapore</figcaption>
          </figure>
          <div className="st-open-txt st-rise">
            <h2 id="st-open-h">Built in the open</h2>
            <p>Visdom is open source and run by FOSSASIA. Want your own server instead? Install Visdom with pip and run it on your machine, the same as always.</p>
            <p>Everything behind visdom.dev is open source too.</p>
            <div className="st-open-links">
              <a href={GITHUB_VISDOM} className="st-btn st-btn-ink">fossasia/visdom</a>
              <a href={GITHUB_VISDOM_DEV} className="st-btn st-btn-ink">fossasia/visdom-dev</a>
            </div>
          </div>
        </section>

        <div className="st-cta-wrap">
          <section className="st-cta" aria-labelledby="st-cta-h">
            <div className="st-flank-l st-shutter">
              <img src="/start/dashboard.png" alt="A Visdom environment with loss, accuracy and learning rate plots" width="1400" height="967" loading="lazy" />
            </div>
            <div className="st-cta-main">
              <h2 id="st-cta-h">Your first plot in five minutes</h2>
              <p>Make an account, create a key and add a few lines to your training script.</p>
              <Link to="/register" className="st-btn st-btn-light">Create an account</Link>
            </div>
            <div className="st-flank-r" />
          </section>
        </div>
      </main>

    </div>
  );
};

export default Start;
