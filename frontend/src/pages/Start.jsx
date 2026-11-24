/* Copyright 2017-present, The Visdom Authors */
import { Link } from 'react-router-dom';
import StartHero from '../components/start/StartHero';
import Chart from '../components/start/Chart';
import { CHARTS } from '../components/start/chartData';
import RunBrowser from '../components/start/RunBrowser';
import FeatureDemos from '../components/start/FeatureDemos';
import { plotSnippet } from '../utils/quickstart';
import '../css/start-sections.css';

const GITHUB_VISDOM = 'https://github.com/fossasia/visdom';
const GITHUB_VISDOM_DEV = 'https://github.com/fossasia/visdom-dev';

const Start = () => {
  return (
    <div className="st-page">
      <main>
        <StartHero />
        <section className="st-steps st-inner" aria-labelledby="st-how">
          <h2 id="st-how">From sign-up to first plot</h2>
          <ol className="st-step-list">
            <li className="st-field">
              <h3>Make a workspace.</h3>
              <div className="st-card">
                <strong>resnet-sweeps</strong><span>Workspace, created just now</span>
                <small>1 member · You, admin</small>
              </div>
            </li>
            <li className="st-field">
              <h3>Give your machine a key.</h3>
              <div className="st-card">
                <strong>lab-gpu-01</strong><span>Key for resnet-sweeps</span>
                <small>Expires in 30 days</small>
              </div>
            </li>
            <li className="st-field">
              <h3>Send a plot.</h3>
              <pre className="st-code" tabIndex="0" aria-label="Connect your script to Visdom"><code>{plotSnippet()}</code></pre>
            </li>
            <li className="st-field">
              <h3>Watch it with your team.</h3>
              <div className="st-team-preview">
                <Chart label="Sample team training loss" lines={CHARTS.loss4} />
                <div className="st-watchers">
                  <span aria-hidden="true"><i>A</i><i>R</i><i>S</i></span>
                  Ana, Raj and Sam watching
                </div>
              </div>
            </li>
          </ol>
        </section>

        <RunBrowser />
        <FeatureDemos />

        <section className="st-open st-inner" aria-labelledby="st-open-h">
          <figure className="st-open-pic">
            <img
              src="/start/fossasia-summit-2019.jpg"
              alt="Group photo of the FOSSASIA Summit 2019 at the Lifelong Learning Institute, Singapore"
              width="1600"
              height="737"
              loading="lazy"
            />
            <figcaption>FOSSASIA Summit 2019, Singapore</figcaption>
          </figure>
          <div className="st-open-txt">
            <h2 id="st-open-h">Built in the open</h2>
            <p>Visdom is open source and run by FOSSASIA. Want your own server instead? Install Visdom with pip and run it on your machine, the same as always.</p>
            <p>Everything behind visdom.dev is open source too.</p>
            <div className="st-open-links">
              <a href={GITHUB_VISDOM} className="st-btn st-btn-ink">fossasia/visdom</a>
              <a href={GITHUB_VISDOM_DEV} className="st-btn st-btn-ink">fossasia/visdom-dev</a>
            </div>
          </div>
        </section>

        <section className="st-cta" aria-labelledby="st-cta-h">
          <div className="st-inner">
            <h2 id="st-cta-h">Your first plot in five minutes</h2>
            <p>Make an account, create a key and add a few lines to your training script.</p>
            <Link to="/register" className="st-btn st-btn-light">Create an account</Link>
          </div>
        </section>
      </main>

    </div>
  );
};

export default Start;
