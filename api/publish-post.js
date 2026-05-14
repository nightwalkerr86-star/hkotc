const DEFAULT_BRANCH = 'main';
const DEFAULT_POSTS_PATH = 'blog-posts.json';

function send(res, status, payload) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.end(JSON.stringify(payload));
}

function env(name, fallback = '') {
  return process.env[name] || fallback;
}

function requireValue(name, value) {
  if (!value) throw new Error('Missing environment variable: ' + name);
  return value;
}

function slugify(value) {
  const base = String(value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff\u1780-\u17ff]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80);
  return base || 'post-' + Date.now();
}

function safeUploadName(fileName = 'cover.jpg') {
  const ext = (String(fileName).match(/.([a-z0-9]+)$/i)?.[1] || 'jpg').toLowerCase().replace('jpeg', 'jpg');
  const base = String(fileName)
    .replace(/.[^.]+$/, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 42) || 'cover';
  return Date.now() + '-' + base + '.' + ext;
}

function normalizeCategory(value) {
  const raw = String(value || '').toLowerCase();
  if (raw.includes('regulation')) return 'Regulation';
  if (raw.includes('guide') || raw.includes('otc')) return 'OTC Guide';
  if (raw.includes('defi')) return 'DeFi';
  return 'Market News';
}

function normalizeExistingPost(post) {
  if (!post || typeof post !== 'object') return null;
  const title = post.title || 'Untitled post';
  const content = post.content || post.body || post.text || '';
  const createdAt = post.createdAt || post.publishedAt || post.updatedAt || (post.date ? new Date(typeof post.date === 'number' ? post.date * 1000 : post.date).toISOString() : new Date().toISOString());
  return {
    id: String(post.id || post.message_id || Date.now()),
    title,
    slug: post.slug || slugify(title),
    category: normalizeCategory(post.category),
    excerpt: post.excerpt || String(content).slice(0, 160),
    content,
    coverImage: post.coverImage || post.photo || '',
    author: post.author || 'HKOTC Desk',
    status: post.status || 'published',
    createdAt,
    updatedAt: post.updatedAt || createdAt,
    publishedAt: post.publishedAt || createdAt,
    date: post.date || Math.floor(new Date(createdAt).getTime() / 1000),
    body: post.body || content,
    photo: post.photo || post.coverImage || '',
    tags: Array.isArray(post.tags) ? post.tags : [],
  };
}

async function githubRequest(url, options = {}) {
  const { token: requestToken, ...fetchOptions } = options;
  const token = requireValue('GITHUB_TOKEN', requestToken || env('GITHUB_TOKEN'));
  const res = await fetch(url, {
    ...fetchOptions,
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      ...(fetchOptions.headers || {}),
    },
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new Error((data && data.message) || 'GitHub request failed: ' + res.status);
  return data;
}

async function getGithubFile(owner, repo, branch, path, token) {
  const url = 'https://api.github.com/repos/' + owner + '/' + repo + '/contents/' + encodeURIComponent(path).replace(/%2F/g, '/') + '?ref=' + encodeURIComponent(branch);
  try {
    const file = await githubRequest(url, token ? { token } : {});
    const json = JSON.parse(Buffer.from(file.content || '', 'base64').toString('utf8'));
    return { data: Array.isArray(json) ? json : [], sha: file.sha };
  } catch (error) {
    if (/Not Found/i.test(error.message)) return { data: [], sha: undefined };
    throw error;
  }
}

async function putGithubFile(owner, repo, branch, path, content, sha, message, token) {
  const url = 'https://api.github.com/repos/' + owner + '/' + repo + '/contents/' + encodeURIComponent(path).replace(/%2F/g, '/');
  const body = { message, branch, content: Buffer.from(content).toString('base64') };
  if (sha) body.sha = sha;
  return githubRequest(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    token,
  });
}

async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
}

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return send(res, 405, { error: 'method_not_allowed' });

  try {
    const payload = await readJsonBody(req);
    const adminPassword = env('ADMIN_PASSWORD') || env('ADMIN_PIN');
    if (adminPassword && !payload.githubToken) {
      const suppliedPassword = req.headers['x-admin-password'] || payload.adminPassword || '';
      if (String(suppliedPassword) !== String(adminPassword)) {
        return send(res, 401, { error: 'unauthorized', message: 'Invalid admin password' });
      }
    }

    const suppliedRepo = String(payload.githubRepo || '').trim();
    const [payloadOwner, payloadRepo] = suppliedRepo.includes('/') ? suppliedRepo.split('/') : ['', ''];
    const token = requireValue('GITHUB_TOKEN', payload.githubToken || env('GITHUB_TOKEN'));
    const owner = requireValue('GITHUB_OWNER', payload.githubOwner || payloadOwner || env('GITHUB_OWNER'));
    const repo = requireValue('GITHUB_REPO', payload.githubRepoName || payloadRepo || env('GITHUB_REPO'));
    const branch = payload.githubBranch || env('GITHUB_BRANCH', DEFAULT_BRANCH);
    const postsPath = payload.githubBlogPath || env('GITHUB_BLOG_PATH', DEFAULT_POSTS_PATH);

    if (payload.verifyOnly) {
      const { data } = await getGithubFile(owner, repo, branch, postsPath, token);
      return send(res, 200, { ok: true, mode: 'verify-only', owner, repo, branch, postsPath, count: data.length });
    }
    if (payload.dryRun) return send(res, 200, { ok: true, mode: 'dry-run', owner, repo, branch, postsPath });

    if (payload.deletePost) {
      const targetPath = payload.githubPath || postsPath;
      const { data: currentPosts, sha } = await getGithubFile(owner, repo, branch, targetPath, token);
      const deleteId = String(payload.id || payload.message_id || '').trim();
      const deleteSlug = String(payload.slug || '').trim();
      const deleteIndex = Number.isInteger(payload.index) ? payload.index : -1;
      let nextPosts = currentPosts.filter((post, index) => {
        if (deleteId && String(post.id || post.message_id || '') === deleteId) return false;
        if (deleteSlug && String(post.slug || '') === deleteSlug) return false;
        if (!deleteId && !deleteSlug && index === deleteIndex) return false;
        return true;
      });
      if (nextPosts.length === currentPosts.length) {
        return send(res, 404, { error: 'post_not_found', message: 'Post not found in GitHub JSON' });
      }
      await putGithubFile(owner, repo, branch, targetPath, JSON.stringify(nextPosts, null, 2) + '\n', sha, 'Delete post', token);
      return send(res, 200, { ok: true, mode: 'delete', count: nextPosts.length });
    }

    const title = String(payload.title || '').trim();
    const content = String(payload.content || payload.body || '').trim();
    if (!title || !content) return send(res, 400, { error: 'invalid_post', message: 'Title and content are required' });

    let coverImage = String(payload.coverImage || '').trim();
    if (payload.coverImageUpload && payload.coverImageUpload.base64) {
      const uploadName = safeUploadName(payload.coverImageUpload.fileName);
      const uploadPath = 'uploads/' + uploadName;
      const imageBuffer = Buffer.from(String(payload.coverImageUpload.base64), 'base64');
      await putGithubFile(owner, repo, branch, uploadPath, imageBuffer, undefined, 'Upload image: ' + uploadName, token);
      coverImage = '/' + uploadPath;
    }

    const now = new Date().toISOString();
    const requestedSlug = slugify(payload.slug || title);
    const { data: currentPosts, sha } = await getGithubFile(owner, repo, branch, postsPath, token);
    const posts = currentPosts.map(normalizeExistingPost).filter(Boolean);
    const usedSlugs = new Set(posts.map(post => post.slug));
    let slug = requestedSlug;
    if (!payload.id) {
      let suffix = 2;
      while (usedSlugs.has(slug)) slug = requestedSlug + '-' + suffix++;
    }

    const post = {
      id: String(payload.id || Date.now()),
      title,
      slug,
      category: normalizeCategory(payload.category),
      excerpt: String(payload.excerpt || content.slice(0, 160)).trim(),
      content,
      coverImage,
      author: 'HKOTC Desk',
      status: 'published',
      createdAt: payload.createdAt || now,
      updatedAt: now,
      publishedAt: payload.publishedAt || now,
      date: Math.floor(Date.now() / 1000),
      body: content,
      photo: coverImage,
      tags: Array.isArray(payload.tags) ? payload.tags : [],
    };

    const existingIndex = posts.findIndex(item => item.id === post.id || item.slug === post.slug);
    if (existingIndex >= 0) posts[existingIndex] = { ...posts[existingIndex], ...post, createdAt: posts[existingIndex].createdAt || post.createdAt };
    else posts.unshift(post);

    posts.sort((a, b) => new Date(b.publishedAt || b.createdAt) - new Date(a.publishedAt || a.createdAt));
    await putGithubFile(owner, repo, branch, postsPath, JSON.stringify(posts, null, 2) + '\n', sha, 'Publish blog post: ' + title, token);

    return send(res, 200, { ok: true, post, count: posts.length });
  } catch (error) {
    return send(res, 500, { error: 'publish_failed', message: error.message });
  }
};
