/* Copyright 2017-present, The Visdom Authors */
import { useEffect, useRef } from 'react';
import { Link, Outlet } from 'react-router-dom';
import { Menu, X } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { CONTROLLER } from '../content/legal';
import '../css/site.css';

const github = 'https://github.com/fossasia/visdom';

function AccountLinks({ children, className }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  return user ? <Link to="/" className={className}>Open dashboard</Link> : children;
}

function Navigation({ onNavigate }) {
  return (
    <nav aria-label="Main navigation" className="site-links" onClick={onNavigate}>
      <Link to="/pricing">Pricing</Link>
      <a href={github}>GitHub</a>
      <AccountLinks className="site-primary">
        <Link to="/login">Sign in</Link>
        <Link to="/register" className="site-primary">Get started</Link>
      </AccountLinks>
    </nav>
  );
}

function SiteHeader({ sticky }) {
  const menu = useRef(null);
  const trigger = useRef(null);

  useEffect(() => {
    const desktop = window.matchMedia?.('(min-width: 768px)');
    const closeOnResize = () => {
      if (desktop.matches && menu.current?.open) menu.current.close();
    };
    desktop?.addEventListener('change', closeOnResize);
    return () => desktop?.removeEventListener('change', closeOnResize);
  }, []);

  return (
    <header className={sticky ? 'site-header site-sticky' : 'site-header'}>
      <Link className="site-brand" to="/" aria-label="Visdom home">
        <img src="/logo.svg" width="30" height="30" alt="" />visdom
      </Link>
      <Navigation />
      <button className="site-menu" ref={trigger} aria-haspopup="dialog"
        aria-controls="site-menu-panel" onClick={() => menu.current.showModal()}>
        <Menu size={20} aria-hidden="true" /> Menu
      </button>
      <dialog id="site-menu-panel" ref={menu} aria-label="Site menu" onClose={() => {
        if (document.activeElement === document.body || menu.current?.contains(document.activeElement)) trigger.current?.focus();
      }}
        onClick={event => { if (event.target === menu.current) menu.current.close(); }}
        onKeyDown={event => {
          if (event.key !== 'Tab') return;
          const links = menu.current.querySelectorAll('button, a');
          const first = links[0];
          const last = links[links.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }}>
        <div className="site-menu-inner">
          <button className="site-menu" onClick={() => menu.current.close()}>
            <X size={20} aria-hidden="true" /> Close menu
          </button>
          <Navigation onNavigate={() => menu.current.close()} />
        </div>
      </dialog>
    </header>
  );
}

function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-footer-links">
        <section>
          <h2>Product</h2>
          <AccountLinks>
            <Link to="/register">Get started</Link>
            <Link to="/login">Sign in</Link>
          </AccountLinks>
          <Link to="/pricing">Pricing</Link>
        </section>
        <section><h2>Open source</h2><a href={github}>fossasia/visdom</a><a href={github + '-dev'}>fossasia/visdom-dev</a></section>
        <section><h2>Legal</h2><Link to="/privacy">Privacy</Link><Link to="/cookies">Cookies</Link><Link to="/terms">Terms</Link></section>
        <section><h2>Contact</h2><Link to="/contact">Contact us</Link></section>
      </div>
      <div className="site-colophon">
        <div>visdom.dev is run by {CONTROLLER.name}, Singapore.</div>
        <Link to="/privacy">© {new Date().getFullYear()} FOSSASIA</Link>
      </div>
      <div className="site-credit">
        <span>Summit photo by Michael Cannon</span>
        <a href="https://commons.wikimedia.org/wiki/File:FOSSASIA_Summit_2019.jpg">Wikimedia Commons</a>
        <a href="https://creativecommons.org/licenses/by-sa/2.0">CC BY-SA 2.0</a>
      </div>
    </footer>
  );
}

export default function SiteLayout({ children, sticky = false }) {
  return (
    <div className="site-layout">
      <SiteHeader sticky={sticky} />
      {children ?? <Outlet />}
      <SiteFooter />
    </div>
  );
}
