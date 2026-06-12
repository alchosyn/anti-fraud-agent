import { useState } from 'react';

interface Props {
  onLogin: (username: string, password: string) => Promise<void>;
  onRegister: (username: string, password: string, displayName: string) => Promise<void>;
}

export default function LoginPage({ onLogin, onRegister }: Props) {
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      if (isRegister) {
        await onRegister(username, password, displayName || username);
      } else {
        await onLogin(username, password);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Operation failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="h-screen flex flex-col items-center justify-center"
      style={{ background: 'linear-gradient(135deg, #e7e7dd, #eee, #dad8d4)' }}
    >
      {/* Header */}
      <div className="mb-10 text-center">
        <div className="w-14 h-14 border-2 border-rl-accent mx-auto mb-4 flex items-center justify-center">
          <svg className="w-7 h-7 text-rl-accent" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
          </svg>
        </div>
        <h1 className="text-lg font-bold tracking-[4px] uppercase text-rl-dark">RHINE LAB</h1>
        <p className="text-[11px] tracking-[2px] uppercase text-rl-muted mt-1">Anti-Fraud Detection System</p>
      </div>

      {/* Form card */}
      <div className="w-full max-w-sm bg-white border border-rl-border p-6">
        {/* Tab switcher */}
        <div className="flex border-b border-rl-border mb-6">
          <button
            type="button"
            onClick={() => { setIsRegister(false); setError(''); }}
            className={`flex-1 py-2 text-[11px] font-bold uppercase tracking-[1.5px] border-b-2 transition-colors ${
              !isRegister ? 'border-rl-accent text-rl-text' : 'border-transparent text-rl-muted'
            }`}
          >
            LOGIN
          </button>
          <button
            type="button"
            onClick={() => { setIsRegister(true); setError(''); }}
            className={`flex-1 py-2 text-[11px] font-bold uppercase tracking-[1.5px] border-b-2 transition-colors ${
              isRegister ? 'border-rl-accent text-rl-text' : 'border-transparent text-rl-muted'
            }`}
          >
            REGISTER
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {isRegister && (
            <div>
              <label className="block text-[10px] font-bold text-rl-muted uppercase tracking-[1.5px] mb-1.5">
                Display Name
              </label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="(optional)"
                className="w-full px-3 py-2 text-sm bg-rl-surface border border-rl-border text-rl-text placeholder:text-rl-border-warm focus:outline-none focus:border-rl-accent"
              />
            </div>
          )}

          <div>
            <label className="block text-[10px] font-bold text-rl-muted uppercase tracking-[1.5px] mb-1.5">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={2}
              className="w-full px-3 py-2 text-sm bg-rl-surface border border-rl-border text-rl-text placeholder:text-rl-border-warm focus:outline-none focus:border-rl-accent"
            />
          </div>

          <div>
            <label className="block text-[10px] font-bold text-rl-muted uppercase tracking-[1.5px] mb-1.5">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              className="w-full px-3 py-2 text-sm bg-rl-surface border border-rl-border text-rl-text placeholder:text-rl-border-warm focus:outline-none focus:border-rl-accent"
            />
          </div>

          {error && (
            <p className="text-[12px] text-red-600 bg-red-50 border border-red-200 px-3 py-2">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-rl-accent text-white text-[11px] font-bold uppercase tracking-[2px] hover:bg-rl-accent/90 disabled:opacity-50 transition-colors"
          >
            {loading ? '...' : isRegister ? 'REGISTER' : 'LOGIN'}
          </button>
        </form>
      </div>

      <p className="mt-6 text-[10px] text-rl-muted tracking-[1px]">
        SIGNAL-TO-NOISE RATIO ANALYSIS PLATFORM
      </p>
    </div>
  );
}
