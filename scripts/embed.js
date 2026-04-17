/**
 * TradeArena Embed Widget v0
 *
 * Usage — add to any page:
 *   <div data-tradearena-profile="alice-quantsworth-a1b2"></div>
 *   <script src="https://tradearena.duckdns.org/assets/embed.js" async></script>
 *
 * Optional attributes:
 *   data-tradearena-theme="dark"   (default) | "light"
 *   data-tradearena-compact="true"           — minimal single-line card
 */
(function () {
  var BASE = (function () {
    var s = document.currentScript;
    if (s && s.src) {
      var u = new URL(s.src);
      return u.origin;
    }
    return 'https://tradearena.duckdns.org';
  })();

  var THEMES = {
    dark: {
      bg: '#16162a', border: '#2a2a40', text: '#e0e0e8',
      muted: '#78788a', accent: '#00c896', accent2: '#9664ff',
    },
    light: {
      bg: '#f8f9fa', border: '#dee2e6', text: '#1a1a2e',
      muted: '#6c757d', accent: '#00a37a', accent2: '#7c4dce',
    },
  };

  function esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderCard(container, profile, compact, t) {
    var score = (profile.scores && profile.scores.composite != null)
      ? profile.scores.composite.toFixed(2) : '—';
    var winRate = (profile.scores && profile.scores.win_rate != null)
      ? (profile.scores.win_rate * 100).toFixed(1) + '%' : '—';
    var level = profile.level || 1;
    var name = esc(profile.display_name || profile.creator_id);
    var div = esc(profile.division || '');
    var profileUrl = BASE + '/profile/' + esc(profile.creator_id);

    var styles = [
      'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif',
      'background:' + t.bg,
      'border:1px solid ' + t.border,
      'border-radius:12px',
      'padding:' + (compact ? '10px 14px' : '16px 20px'),
      'color:' + t.text,
      'max-width:' + (compact ? '420px' : '360px'),
      'box-sizing:border-box',
      'text-decoration:none',
      'display:block',
      'line-height:1.4',
    ].join(';');

    if (compact) {
      container.innerHTML =
        '<a href="' + profileUrl + '" target="_blank" rel="noopener" style="' + styles + '">' +
        '<span style="font-weight:600;color:' + t.text + '">' + name + '</span>' +
        '<span style="margin-left:8px;font-size:12px;color:' + t.muted + '">Lv.' + level + ' · ' + div + '</span>' +
        '<span style="float:right;font-size:13px;color:' + t.accent + '">' + score + ' score</span>' +
        '</a>';
      return;
    }

    var avatar = '';
    if (profile.github_avatar_url) {
      avatar = '<img src="' + esc(profile.github_avatar_url) + '" alt="" ' +
        'style="width:48px;height:48px;border-radius:50%;border:2px solid ' + t.accent + ';object-fit:cover">';
    } else {
      avatar = '<div style="width:48px;height:48px;border-radius:50%;background:' + t.accent +
        ';display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:700;color:#000">' +
        esc((profile.display_name || 'T').charAt(0).toUpperCase()) + '</div>';
    }

    container.innerHTML =
      '<a href="' + profileUrl + '" target="_blank" rel="noopener" style="' + styles + '">' +
      '<div style="display:flex;gap:12px;align-items:center;margin-bottom:14px">' +
        avatar +
        '<div>' +
          '<div style="font-weight:700;font-size:16px">' + name + '</div>' +
          '<div style="font-size:12px;color:' + t.muted + '">' +
            'Level ' + level + ' · ' + div +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">' +
        _statBox('Score', score, t.accent, t) +
        _statBox('Win Rate', winRate, winRate !== '—' && parseFloat(winRate) >= 50 ? '#22c55e' : t.muted, t) +
      '</div>' +
      '<div style="margin-top:14px;font-size:11px;color:' + t.muted + ';text-align:right">' +
        'TradeArena · Not investment advice' +
      '</div>' +
      '</a>';
  }

  function _statBox(label, value, color, t) {
    return '<div style="background:rgba(255,255,255,0.04);border:1px solid ' + t.border +
      ';border-radius:8px;padding:10px;text-align:center">' +
      '<div style="font-size:20px;font-weight:700;color:' + color + '">' + esc(value) + '</div>' +
      '<div style="font-size:11px;color:' + t.muted + ';text-transform:uppercase;letter-spacing:.04em">' + esc(label) + '</div>' +
      '</div>';
  }

  function renderError(container, msg, t) {
    container.innerHTML = '<div style="font-family:sans-serif;font-size:13px;color:' +
      (t ? t.muted : '#888') + ';padding:10px;border:1px solid #333;border-radius:8px">' +
      'TradeArena widget: ' + esc(msg) + '</div>';
  }

  function initWidget(container) {
    var creatorId = container.getAttribute('data-tradearena-profile');
    if (!creatorId) return;

    var themeKey = (container.getAttribute('data-tradearena-theme') || 'dark').toLowerCase();
    var t = THEMES[themeKey] || THEMES.dark;
    var compact = container.getAttribute('data-tradearena-compact') === 'true';

    container.style.display = 'block';

    var url = BASE + '/api/v1/users/' + encodeURIComponent(creatorId) + '/profile';
    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error('Creator not found');
        return r.json();
      })
      .then(function (profile) {
        renderCard(container, profile, compact, t);
      })
      .catch(function (e) {
        renderError(container, e.message, t);
      });
  }

  function init() {
    var containers = document.querySelectorAll('[data-tradearena-profile]');
    for (var i = 0; i < containers.length; i++) {
      initWidget(containers[i]);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
