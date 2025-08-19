{% extends "base.html" %}
{% block title %}Support · Domovra{% endblock %}

{% block content %}
<div class="container" style="max-width:780px;margin:0 auto;padding:1.25rem;">
  <h1 style="margin:0 0 0.5rem 0;">Support ❤️</h1>
  <p style="opacity:0.9;line-height:1.6;">
    Domovra est un add‑on open‑source pour Home Assistant qui simplifie la gestion de votre stock domestique.
    Si vous appréciez le projet et souhaitez qu’il continue à évoluer, vous pouvez m’offrir un café ☕.
  </p>

  <div style="display:flex;gap:1rem;align-items:center;margin:1rem 0 1.5rem 0;">
    <!-- Bouton Ko-fi (image officielle) -->
    <a href="https://ko-fi.com/domovra" target="_blank" rel="noopener"
       style="display:inline-flex;align-items:center;text-decoration:none;border:1px solid var(--ha-card-border-color,#E0E0E0);
              padding:0.6rem 0.9rem;border-radius:999px;font-weight:600;">
      <img src="https://storage.ko-fi.com/cdn/kofi3.png?v=3" alt="Buy Me a Coffee at ko-fi.com"
           style="height:24px;width:auto;margin-right:0.6rem;">
      <span>Support on Ko‑fi</span>
    </a>

    <!-- Lien simple en secours -->
    <a href="https://ko-fi.com/domovra" target="_blank" rel="noopener"
       style="text-decoration:underline;">ko-fi.com/domovra</a>
  </div>

  <details>
    <summary style="cursor:pointer;font-weight:600;">À quoi servent les dons&nbsp;?</summary>
    <ul style="margin:0.6rem 0 0 1.25rem;">
      <li>Hébergement de la doc &amp; outils</li>
      <li>Temps de dev (corrections &amp; nouvelles features)</li>
      <li>Matériel de test</li>
    </ul>
  </details>

  <hr style="margin:1.5rem 0;opacity:0.2;">
  <p class="muted" style="font-size:0.95rem;">
    Merci pour votre soutien. Les dons sont facultatifs et n’ouvrent aucune contrepartie payante.
  </p>
</div>
{% endblock %}
