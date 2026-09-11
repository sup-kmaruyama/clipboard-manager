// Cloudflare Pages 全体に HTTP Basic 認証をかけるミドルウェア。
// ユーザー名・パスワードは Cloudflare Pages の環境変数(Secret)
// BASIC_AUTH_USER / BASIC_AUTH_PASS から取得する(コードには書かない)。
export async function onRequest(context) {
  const { request, env, next } = context;

  const expectedUser = env.BASIC_AUTH_USER;
  const expectedPass = env.BASIC_AUTH_PASS;

  // Secret未設定の場合は誤って無認証公開しないようブロックする。
  if (!expectedUser || !expectedPass) {
    return new Response("Basic auth is not configured.", { status: 500 });
  }

  const authHeader = request.headers.get("Authorization");
  if (authHeader && authHeader.startsWith("Basic ")) {
    const decoded = atob(authHeader.slice(6));
    const separatorIndex = decoded.indexOf(":");
    const user = decoded.slice(0, separatorIndex);
    const pass = decoded.slice(separatorIndex + 1);

    if (user === expectedUser && pass === expectedPass) {
      return next();
    }
  }

  return new Response("Authentication required.", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="clipboard-manager"',
    },
  });
}
