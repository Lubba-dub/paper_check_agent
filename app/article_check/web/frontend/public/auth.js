(() => {
  const searchParams = new URLSearchParams(window.location.search);
  const defaultConfig = {
    enabled: false,
    mode: 'legacy_oauth',
    apiBase: '/prod-api',
    host: 'http://124.71.226.114:8444',
    callbackPath: '/auth/login',
    storagePrefix: 'article_check_platform_',
    debug: false,
  };

  bootstrap().catch((error) => {
    console.error('platform auth bootstrap error:', error);
  });

  async function bootstrap() {
    const runtimeConfig = await loadRuntimeConfig();
    const config = {
      ...defaultConfig,
      ...runtimeConfig,
    };
    if (searchParams.has('forcePlatformAuth')) {
      config.enabled = true;
    }
    if (searchParams.has('authMode')) {
      config.mode = searchParams.get('authMode');
    }
    if (searchParams.has('authApiBase')) {
      config.apiBase = searchParams.get('authApiBase');
    }

    const log = (...args) => {
      if (config.debug) {
        console.log('[platform-auth]', ...args);
      }
    };

    if (!config.enabled) {
      log('平台认证脚本已加载，但当前环境未启用认证。');
      return;
    }

    const accessTokenKey = `${config.storagePrefix}access_token`;
    const refreshTokenKey = `${config.storagePrefix}refresh_token`;
    const idTokenKey = `${config.storagePrefix}id_token`;
    const expiresInKey = `${config.storagePrefix}expires_in`;
    const userInfoKey = `${config.storagePrefix}user_info`;
    const returnToKey = `${config.storagePrefix}return_to`;

    const API = {
      LEGACY_OAUTH: {
        AUTH: `${config.host}/api/oauth/auth`,
        TOKEN: `${config.host}/api/oauth/token`,
        REFRESH: `${config.host}/api/oauth/refresh`,
        INTROSPECT: `${config.host}/api/oauth/introspect`,
      },
      PROD_API_IDP: {
        AUTH: `${config.apiBase}/auth/idp/auth`,
        TOKEN_BY_CODE: `${config.apiBase}/auth/idp/get-token-by-auth-code`,
        GET_INFO: `${config.apiBase}/system/user/idp/getInfo`,
        GET_ROUTERS: `${config.apiBase}/system/menu/getRouters`,
      },
    };

    installFetchInterceptor();

    auth().then((ok) => {
      if (!ok) {
        alert('平台认证失败，请联系管理员检查 OAuth 配置。');
      }
    });

    async function auth() {
    const code = searchParams.get('code');
    const state = searchParams.get('state');

    if (!code) {
      const accessToken = localStorage.getItem(accessTokenKey);
      if (!accessToken) {
        return redirect();
      }

      if (config.mode === 'prod_api_idp') {
        return validateProdApiSession();
      }

      const expiresIn = localStorage.getItem(expiresInKey);
      if (expiresIn && Date.now() > Number(expiresIn)) {
        return refreshToken();
      }
      return introspectToken();
    }

    log('oauth callback', { code, state });
    const result = await getToken(code, state);
    const returnTo = localStorage.getItem(returnToKey) || '/';
    localStorage.removeItem(returnToKey);
    window.history.replaceState({}, document.title, returnTo);
    return result;
  }

    async function redirect() {
    if (window.location.pathname !== config.callbackPath) {
      localStorage.setItem(
        returnToKey,
        `${window.location.pathname}${window.location.search}${window.location.hash}`
      );
    }

    if (config.mode === 'prod_api_idp') {
      const redirectUri = `${window.location.origin}${config.callbackPath}`;
      const url = `${API.PROD_API_IDP.AUTH}?redirectUri=${encodeURIComponent(redirectUri)}`;

      try {
        const result = await fetchJson(url);
        const authUrl = unwrapData(result);
        if (!authUrl) {
          throw new Error('missing auth url');
        }
        window.location.href = authUrl;
        return true;
      } catch (error) {
        console.error('redirect prod-api auth error:', error);
        return false;
      }
    }

    if (!config.host) {
      console.error('legacy oauth host is not configured');
      return false;
    }

    const redirectUri = window.location.origin + window.location.pathname;
    const url = `${API.LEGACY_OAUTH.AUTH}?redirectUri=${encodeURIComponent(redirectUri)}`;

    try {
      const result = await fetchJson(url);
      window.location.href = result.auth_url;
      return true;
    } catch (error) {
      console.error('redirect auth error:', error);
      return false;
    }
  }

    async function getToken(code) {
    if (config.mode === 'prod_api_idp') {
      try {
        const result = await fetchJson(`${API.PROD_API_IDP.TOKEN_BY_CODE}/${encodeURIComponent(code)}`);
        const data = unwrapData(result) || {};
        const accessToken = data.accessToken || data.access_token || '';
        const refreshToken = data.refreshToken || data.refresh_token || '';
        const idToken = data.idToken || data.id_token || '';
        const expiresIn = data.expiresIn || data.expires_in || 3600;

        if (!accessToken) {
          throw new Error('missing accessToken');
        }

        localStorage.setItem(accessTokenKey, accessToken);
        localStorage.setItem(refreshTokenKey, refreshToken);
        localStorage.setItem(idTokenKey, idToken);
        localStorage.setItem(expiresInKey, Date.now() + (Number(expiresIn) * 1000));

        await loadUserInfo();
        await warmRouters();
        return true;
      } catch (error) {
        console.error('get prod-api token error:', error);
        clearTokens();
        return false;
      }
    }

    if (!config.host) {
      console.error('legacy oauth host is not configured');
      return false;
    }

    const raw = JSON.stringify({
      code,
      redirect_uri: window.location.origin + window.location.pathname,
    });

    try {
      const result = await fetchJson(API.LEGACY_OAUTH.TOKEN, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: raw,
        redirect: 'follow',
      });
      localStorage.setItem(accessTokenKey, result.access_token);
      localStorage.setItem(refreshTokenKey, result.refresh_token);
      localStorage.setItem(idTokenKey, result.id_token);
      localStorage.setItem(expiresInKey, Date.now() + (result.expires_in * 1000));
      return true;
    } catch (error) {
      console.error('get token error:', error);
      return false;
    }
  }

    async function refreshToken() {
    try {
      const result = await fetchJson(API.LEGACY_OAUTH.REFRESH, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          refresh_token: localStorage.getItem(refreshTokenKey),
        }),
        redirect: 'follow',
      });
      localStorage.setItem(accessTokenKey, result.access_token);
      localStorage.setItem(refreshTokenKey, result.refresh_token);
      localStorage.setItem(idTokenKey, result.id_token);
      localStorage.setItem(expiresInKey, Date.now() + (result.expires_in * 1000));
      return true;
    } catch (error) {
      console.error('refresh token error:', error);
      return false;
    }
  }

    async function introspectToken() {
    try {
      const result = await fetchJson(API.LEGACY_OAUTH.INTROSPECT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token: localStorage.getItem(accessTokenKey),
        }),
        redirect: 'follow',
      });
      if (result.active !== true) {
        return redirect();
      }
      return true;
    } catch (error) {
      console.error('introspect token error:', error);
      return false;
    }
  }

    async function validateProdApiSession() {
    try {
      await loadUserInfo();
      return true;
    } catch (error) {
      console.error('validate prod-api session error:', error);
      clearTokens();
      return redirect();
    }
  }

    async function loadUserInfo() {
    const result = await fetchJson(API.PROD_API_IDP.GET_INFO, {
      method: 'GET',
      headers: buildAuthHeaders(),
    });
    const data = unwrapData(result) || {};
    localStorage.setItem(userInfoKey, JSON.stringify(data));
    window.__ARTICLE_CHECK_AUTH_CONTEXT__ = data;
    return data;
  }

    async function warmRouters() {
    try {
      await fetchJson(API.PROD_API_IDP.GET_ROUTERS, {
        method: 'GET',
        headers: buildAuthHeaders(),
      });
    } catch (error) {
      log('warm routers failed', error);
    }
  }

    function buildAuthHeaders(extraHeaders = {}) {
    const accessToken = localStorage.getItem(accessTokenKey);
    const refreshToken = localStorage.getItem(refreshTokenKey);
    const headers = { ...extraHeaders };
    if (accessToken) {
      headers.Authorization = accessToken.startsWith('Bearer ')
        ? accessToken
        : `Bearer ${accessToken}`;
    }
    if (refreshToken) {
      headers['refresh-token'] = refreshToken.startsWith('Bearer ')
        ? refreshToken
        : `Bearer ${refreshToken}`;
    }
    return headers;
  }

    function clearTokens() {
    localStorage.removeItem(accessTokenKey);
    localStorage.removeItem(refreshTokenKey);
    localStorage.removeItem(idTokenKey);
    localStorage.removeItem(expiresInKey);
    localStorage.removeItem(userInfoKey);
  }

    function installFetchInterceptor() {
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, init = {}) => {
      const url = typeof input === 'string' ? input : input?.url || '';
      if (!shouldAttachAuthHeaders(url)) {
        return originalFetch(input, init);
      }
      const mergedHeaders = buildAuthHeaders(normalizeHeaders(init.headers));
      return originalFetch(input, {
        ...init,
        headers: mergedHeaders,
      });
    };
  }

    function shouldAttachAuthHeaders(url) {
    const backendApiMatch =
      url.startsWith('/api/') ||
      url === '/api' ||
      url.includes(`${window.location.origin}/api/`);
    const normalizedApiBase = String(config.apiBase || '').replace(/\/$/, '');
    const prodApiMatch =
      normalizedApiBase &&
      (url === normalizedApiBase ||
        url.startsWith(`${normalizedApiBase}/`) ||
        url.includes(`${window.location.origin}${normalizedApiBase}/`));
    if (backendApiMatch) {
      return true;
    }
    if (config.mode !== 'prod_api_idp') {
      return false;
    }
    if (prodApiMatch) {
      return true;
    }
    return url.startsWith('/prod-api/') || url.includes(`${window.location.origin}/prod-api/`);
  }

    function normalizeHeaders(headers) {
    if (!headers) {
      return {};
    }
    if (headers instanceof Headers) {
      const plain = {};
      headers.forEach((value, key) => {
        plain[key] = value;
      });
      return plain;
    }
    return { ...headers };
  }

    async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`${response.status} ${text}`);
    }
    return response.json();
  }

    function unwrapData(result) {
    if (result && typeof result === 'object' && 'data' in result) {
      return result.data;
    }
    return result;
  }

    async function loadRuntimeConfig() {
      try {
        const response = await fetch('/api/platform-auth-config', { credentials: 'same-origin' });
        if (!response.ok) {
          return window.__ARTICLE_CHECK_PLATFORM_AUTH__ || {};
        }
        return await response.json();
      } catch (error) {
        console.warn('load platform auth config failed:', error);
        return window.__ARTICLE_CHECK_PLATFORM_AUTH__ || {};
      }
    }
  }
})();
