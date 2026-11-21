<template>
  <header>
    <div class="header-shell">
      <div class="header-brand">
        <img class="logo" src="/img/logo.webp" alt="" />
        <h1>找个搭子</h1>
      </div>
      <nav v-if="user" id="mobile-nav" ref="mobileNav" aria-label="站点导航" :class="{open: menuOpen}" @touchstart="onDrawerTouchStart" @touchend="onDrawerTouchEnd">
        <div class="nav-mobile-only nav-mobile-head">
          <strong>菜单</strong>
          <button type="button" class="ghost drawer-close" @click="closeDrawer()" aria-label="关闭菜单">×</button>
        </div>
        <button type="button" class="nav-item" :aria-current="navCurrent === 'hall' ? 'page' : undefined" @click="go('hall')">活动大厅</button>
        <button type="button" class="nav-item" :aria-current="navCurrent === 'my' ? 'page' : undefined" @click="go('my')">我的活动</button>
        <button type="button" class="nav-item" :aria-current="navCurrent === 'notif' ? 'page' : undefined" @click="go('notif')" :aria-label="unread ? '通知，未读 ' + unread + ' 条' : '通知'">通知<span v-if="unread" class="unread-badge" aria-hidden="true">{{ unread > 99 ? '99+' : unread }}</span></button>
        <button type="button" class="nav-item nav-cta" :aria-current="navCurrent === 'publish' ? 'page' : undefined" @click="go('publish')">发布活动</button>
        <p class="nav-mobile-greet nav-mobile-only">你好，{{ user.nickname }}（{{ user.account }}）</p>
        <button v-if="user.is_admin" type="button" class="nav-item nav-mobile-only" :aria-current="view === 'admin' ? 'page' : undefined" @click="go('admin')">治理工作台</button>
        <button type="button" class="nav-item nav-mobile-only" :aria-current="view === 'profile' ? 'page' : undefined" @click="openProfile">个人资料</button>
        <button type="button" class="nav-item nav-mobile-only" :aria-current="view === 'password' ? 'page' : undefined" @click="go('password')">修改密码</button>
        <button type="button" class="nav-mobile-only" @click="toggleTheme">切换为{{ darkMode ? '浅色' : '深色' }}模式</button>
        <button type="button" class="nav-mobile-only" @click="logout">退出登录</button>
      </nav>
      <div v-if="!user" class="header-right header-right-anon">
        <button class="ghost theme-btn" @click="toggleTheme" :aria-pressed="darkMode"><span class="theme-icon">{{ darkMode ? '☀️' : '🌙' }}</span><span class="theme-label">{{ darkMode ? ' 浅色模式' : ' 深色模式' }}</span><span class="theme-label-short">{{ darkMode ? ' 浅色' : ' 深色' }}</span></button>
      </div>
      <div v-else class="header-right" :inert="menuOpen">
        <div ref="userMenu" class="user-menu" @focusout="onUserMenuFocusOut" @keydown.esc.stop="closeUserMenu(true)">
          <button ref="userMenuBtn" type="button" class="user-menu-btn" :class="{'account-current': ['profile', 'password', 'admin'].includes(view)}" @click="userMenuOpen = !userMenuOpen" :aria-label="'账户选项：' + user.nickname" :aria-expanded="userMenuOpen" aria-controls="account-actions">
            <span class="user-menu-name">{{ user.nickname }}</span><span aria-hidden="true">▾</span>
          </button>
          <div v-show="userMenuOpen" id="account-actions" class="user-menu-pop">
            <p class="user-menu-greet"><strong>{{ user.nickname }}</strong><span>{{ user.account }}</span></p>
            <button v-if="user.is_admin" type="button" :aria-current="view === 'admin' ? 'page' : undefined" @click="userMenuRun(() => go('admin'))">治理工作台</button>
            <button type="button" :aria-current="view === 'profile' ? 'page' : undefined" @click="userMenuRun(openProfile)">个人资料</button>
            <button type="button" :aria-current="view === 'password' ? 'page' : undefined" @click="userMenuRun(() => go('password'))">修改密码</button>
            <button type="button" @click="userMenuRun(toggleTheme)">切换为{{ darkMode ? '浅色' : '深色' }}模式</button>
            <hr class="user-menu-sep" />
            <button type="button" @click="userMenuRun(logout)">退出登录</button>
          </div>
        </div>
        <button ref="menuBtn" type="button" class="menu-btn" @click="menuOpen = !menuOpen" :aria-expanded="menuOpen" aria-controls="mobile-nav" :aria-label="unread ? '菜单，通知未读 ' + unread + ' 条' : '菜单'">☰ 菜单<span v-if="unread" class="menu-unread-dot" aria-hidden="true"></span></button>
      </div>
    </div>
    <div v-if="user && menuOpen" class="nav-backdrop" @click="closeDrawer()"></div>
  </header>
  <div class="site-notice">本网站仅用于课程设计展示使用，不对外开放</div>
  <main :class="{'workspace-main': user && (view === 'hall' || view === 'roster')}" :inert="menuOpen">
    <div v-if="msg && !authModal.visible" class="msg">{{ msg }}<button v-if="msgAction && msg === msgAction.text" class="ghost msg-action" @click="msgAction.run()">查看我报名的活动</button><button class="msg-close" @click="msg=''" aria-label="关闭提示">×</button></div>
    <p v-if="!user && loginHint && view!=='recovery' && view!=='register'" class="hint">还没有账号？<button type="button" class="link-btn" @click="goAuth('register')">注册新账号</button></p>
    <div v-if="withdrawNotice" class="msg withdraw-notice" aria-live="polite">
      <b>{{ withdrawNotice.text }}</b><span v-if="!resignupBusy">手抖点错了？</span>
      <button class="primary" :disabled="signupLocked" @click="resignupFromNotice"><b>{{ resignupBusy ? '正在报名…' : '点这里重新报名' }}</b></button>
    </div>

    <section v-if="!user && view!=='recovery' && view!=='register'" class="login-page">
      <div class="hero-banner"><img src="/img/hero.webp" alt="找个搭子：一起打球、玩桌游、学习" /></div>
      <h2 class="login-welcome">欢迎来到找个搭子</h2>
      <p class="meta login-sub">先睹为快：以下是大厅活动一览，登录后可查看详情、报名参加</p>
      <div class="login-hall-summary">
        <h3>当前大厅 {{ loginHall.length }} 个活动</h3>
        <p v-for="a in loginHall" :key="'login-hall-' + a.id">{{ a.title }} 正式 {{ a.formal_count }}/{{ a.capacity }}<span v-if="a.start_time"> · {{ fmtWeekdayHM(a.start_time) }}</span><span v-if="a.status === 'ENDED'"> · 已结束</span><span v-else-if="isFull(a)"> · 已满员</span><span v-else-if="deadlinePassed(a)"> · 已截止</span></p>
      </div>
      <div class="card login auth-card">
      <h3>登录</h3>
      <form @submit.prevent="login">
        <label class="field-label" for="login-account">账号（必填）</label>
        <input id="login-account" v-model="account" placeholder="账号" autocomplete="username" :aria-invalid="loginErrors.account ? 'true' : undefined" aria-describedby="login-account-slot" />
        <p id="login-account-slot" class="field-slot" :class="{'field-error': loginErrors.account}" :role="loginErrors.account ? 'alert' : undefined">{{ loginErrors.account }}</p>
        <label class="field-label" for="login-password">密码（必填）</label>
        <div class="pwd-row">
          <input id="login-password" v-model="password" :type="showPwdLogin ? 'text' : 'password'" placeholder="密码" autocomplete="current-password" :aria-invalid="loginErrors.password ? 'true' : undefined" aria-describedby="login-password-slot" />
          <button type="button" class="pwd-eye" :aria-pressed="showPwdLogin" :aria-label="showPwdLogin ? '隐藏密码' : '显示密码'" @click="showPwdLogin = !showPwdLogin"><EyeOff v-if="showPwdLogin" :size="20" aria-hidden="true" /><Eye v-else :size="20" aria-hidden="true" /></button>
        </div>
        <p id="login-password-slot" class="field-slot" :class="{'field-error': loginErrors.password}" :role="loginErrors.password ? 'alert' : undefined">{{ loginErrors.password }}</p>
        <button id="login-submit" type="submit" class="primary auth-primary" :disabled="loginBusy">{{ loginBusy ? '提交中…' : '登录' }}</button>
      </form>
      <details class="demo-login">
        <summary>演示：以以下身份进入</summary>
        <select id="quick-account" v-model="quickAccount" aria-label="演示账号选择">
          <option value="">请选择账号</option>
          <option value="organizer">组织者</option>
          <option value="admin">管理员</option>
          <option value="demo01">同学1</option>
          <option value="demo05">同学5（桌游候补）</option>
        </select>
        <button type="button" class="ghost" @click="quick(quickAccount)">以该身份进入（演示）</button>
        <p class="hint">演示账号一键进入，无需输入密码，也可注册新账号。</p>
      </details>
      <template v-if="isCapacitor">
      <label class="field-label" for="login-apibase">后端地址（仅手机 App 用）</label>
      <input id="login-apibase" v-model="apiBase" placeholder="后端地址" @change="saveApiBase" />
      <p class="hint">手机 App 才填后端地址，如 http://192.168.1.5:8080；网页 / PWA 留空，用当前地址。</p>
      </template>
      <button type="button" class="ghost recovery-entry" @click="go('recovery')">忘记密码 / 账号被封禁？提交恢复申请</button>
      <div class="auth-switch-row">还没有账号？<button type="button" class="link-btn" @click="goAuth('register')">注册新账号</button></div>
      </div>
    </section>

    <section v-if="!user && view==='register'" class="register-page">
      <h2 class="login-welcome">欢迎加入找个搭子</h2>
      <p class="meta login-sub">注册后可报名活动、接收递补通知；站内只用昵称展示，不公开联系方式。</p>
      <div class="card auth-card">
        <h3>注册新账号</h3>
        <form @submit.prevent="submitRegister">
          <label class="field-label" for="reg-account">账号（必填）</label>
          <input id="reg-account" v-model="account" placeholder="如学号或自定账号" autocomplete="username" @blur="onRegBlur('account')" @input="onRegInput('account')" :aria-invalid="regErrors.account ? 'true' : undefined" aria-describedby="reg-account-slot" />
          <p id="reg-account-slot" class="field-slot" :class="{'field-error': regErrors.account}" :role="regErrors.account ? 'alert' : undefined">{{ regErrors.account || '4–32 个字符，区分大小写' }}</p>
          <label class="field-label" for="reg-password">密码（必填）</label>
          <div class="pwd-row">
            <input id="reg-password" v-model="password" :type="showPwdReg ? 'text' : 'password'" placeholder="8–64 位，含字母与数字" autocomplete="new-password" aria-describedby="reg-password-slot" :aria-invalid="regPwdServerError ? 'true' : undefined" @input="onConfirmInput" />
            <button type="button" class="pwd-eye" :aria-pressed="showPwdReg" :aria-label="showPwdReg ? '隐藏密码' : '显示密码'" @click="showPwdReg = !showPwdReg"><EyeOff v-if="showPwdReg" :size="20" aria-hidden="true" /><Eye v-else :size="20" aria-hidden="true" /></button>
          </div>
          <p v-if="regPwdServerError" id="reg-password-slot" class="field-slot field-error" role="alert">{{ regPwdServerError }}</p>
          <ul class="pwd-rules">
            <li :class="{ok: pwdRuleLen}"><span class="tick">{{ pwdRuleLen ? '✓' : '○' }}</span> 8–64 位</li>
            <li :class="{ok: pwdRuleLetter}"><span class="tick">{{ pwdRuleLetter ? '✓' : '○' }}</span> 含字母</li>
            <li :class="{ok: pwdRuleDigit}"><span class="tick">{{ pwdRuleDigit ? '✓' : '○' }}</span> 含数字</li>
          </ul>
          <p class="field-hint">{{ (pwdRuleLen && pwdRuleLetter && pwdRuleDigit) ? '已满足建议强度' : '以上为建议强度，未全满足仍可注册。' }}</p>
          <label class="field-label" for="reg-password-confirm">确认密码（必填）</label>
          <div class="pwd-row">
            <input id="reg-password-confirm" v-model="passwordConfirm" :type="showPwdReg ? 'text' : 'password'" placeholder="再次输入相同的密码" autocomplete="new-password" aria-describedby="reg-confirm-slot" :aria-invalid="regConfirmError ? 'true' : undefined" @input="onConfirmInput" />
          </div>
          <p id="reg-confirm-slot" class="field-slot" :class="{'field-error': regConfirmError}" :role="regConfirmError ? 'alert' : undefined">{{ regConfirmError || '请再次输入密码，两次保持一致' }}</p>
          <label class="field-label" for="reg-nickname">昵称（可选）</label>
          <input id="reg-nickname" v-model="nickname" placeholder="不填则取账号前 30 字" autocomplete="nickname" @blur="onRegBlur('nickname')" @input="onRegInput('nickname')" :aria-invalid="regErrors.nickname ? 'true' : undefined" aria-describedby="reg-nickname-slot" />
          <p id="reg-nickname-slot" class="field-slot" :class="{'field-error': regErrors.nickname}" :role="regErrors.nickname ? 'alert' : undefined">{{ regErrors.nickname || '可不填；不填时用账号前 30 字，最多 30 字。' }}</p>
          <button id="reg-submit" type="submit" class="primary auth-primary" :disabled="registerBusy">{{ registerBusy ? '提交中…' : '注册新账号' }}</button>
        </form>
        <div class="auth-switch-row">已有账号？<button type="button" class="link-btn" @click="goAuth('login')">去登录</button></div>
      </div>
      <p class="hint">账号可自定（建议用学号），没有学号也可以注册。</p>
    </section>

    <section v-if="!user && view==='recovery'" class="login-page recovery-page">
      <div class="card recovery-card">
        <h3>账号恢复申请</h3>
        <p class="meta">忘记密码、或账号被封禁需要复核，都可在这里提交申请。提交后请保存好申请编号与查询凭据，凭据只显示一次。</p>
        <p v-if="recoveryMine && recoveryMine.id" class="saved-creds">
          本机已保存申请：编号 <b>{{ recoveryMine.id }}</b><span v-if="recoveryMine.query_token">，查询凭据 <b>{{ recoveryMine.query_token }}</b></span>
        </p>
        <label class="field-label" for="rec-account">账号</label>
        <input id="rec-account" v-model="recoveryForm.account" placeholder="你的账号" autocomplete="username" />
        <label class="field-label" for="rec-type">申请类型</label>
        <select id="rec-type" v-model.number="recoveryForm.request_type">
          <option :value="1">1 密码找回</option>
          <option :value="2">2 封禁复核</option>
        </select>
        <label class="field-label" for="rec-contact">联系方式</label>
        <input id="rec-contact" v-model="recoveryForm.contact" placeholder="手机号 / 邮箱，便于管理员联系" />
        <label class="field-label" for="rec-reason">理由</label>
        <textarea id="rec-reason" v-model="recoveryForm.reason" rows="3" maxlength="2000" placeholder="说明情况，如忘记密码、对封禁有异议"></textarea>
        <button class="primary" :disabled="recoveryBusy" @click="submitRecovery">{{ recoveryBusy ? '提交中…' : '提交申请' }}</button>
      </div>
      <div class="card recovery-card">
        <h3>查询申请进度</h3>
        <label class="field-label" for="rec-qid">申请编号</label>
        <input id="rec-qid" v-model="recoveryQueryForm.id" placeholder="提交后得到的申请编号" />
        <label class="field-label" for="rec-qtoken">查询凭据</label>
        <input id="rec-qtoken" v-model="recoveryQueryForm.query_token" placeholder="提交后得到的查询凭据" />
        <button class="ghost" :disabled="recoveryQueryBusy" @click="queryRecovery">{{ recoveryQueryBusy ? '查询中…' : '查询状态' }}</button>
        <div v-if="recoveryStatusData">
          <p class="info-line"><span class="info-label">状态</span><b>{{ recoveryStateText(recoveryStatusData.state) }}</b></p>
          <p class="meta">申请时间：<span class="nowrap">{{ fmtWeek(recoveryStatusData.applied_at) }}</span><span v-if="recoveryStatusData.reviewed_at">　审核时间：<span class="nowrap">{{ fmtWeek(recoveryStatusData.reviewed_at) }}</span></span></p>
          <p v-if="recoveryStatusData.state === 'APPROVED' && recoveryStatusData.has_reset_credential" class="saved-creds">管理员已批准，请向管理员索取重置凭据后在下方使用<span v-if="recoveryStatusData.reset_expires_at">（凭据于 <span class="nowrap">{{ fmtWeek(recoveryStatusData.reset_expires_at) }}</span> 前有效）</span>。</p>
          <p v-else-if="recoveryStatusData.state === 'COMPLETED'" class="hint">密码已重置完成，可直接返回登录。</p>
        </div>
      </div>
      <div class="card recovery-card">
        <h3>使用重置凭据</h3>
        <p class="meta">向管理员取得重置凭据后，在此设置新密码。</p>
        <label class="field-label" for="rec-credential">重置凭据</label>
        <input id="rec-credential" v-model="resetForm.credential" placeholder="管理员转交的重置凭据" />
        <label class="field-label" for="rec-newpw">新密码</label>
        <input id="rec-newpw" v-model="resetForm.new_password" type="password" autocomplete="new-password" placeholder="8–64 位，含字母与数字" />
        <button class="primary" :disabled="resetBusy" @click="useResetCredential">{{ resetBusy ? '提交中…' : '重置密码' }}</button>
        <p class="hint">凭据一次性有效，成功后需回登录页用新密码登录。</p>
      </div>
      <button class="ghost" @click="backToLogin">← 返回登录</button>
    </section>

    <section v-if="user && view==='hall'">
      <div v-if="!searchNoResult" class="hero-banner"><img src="/img/hero.webp" alt="找个搭子：一起打球、玩桌游、学习" /></div>
      <div class="card hall-tools">
        <input v-model="q" aria-label="搜索活动" placeholder="试试搜：羽毛球、自习" />
        <select v-model="campus" aria-label="按校区筛选">
          <option value="">全部校区</option><option>望江</option><option>华西</option><option>江安</option><option>其他</option>
        </select>
        <select v-model="timeSlot" aria-label="按时间段筛选">
          <option value="">全部时段</option><option value="今天">今天</option><option value="周末">周末（周六/周日）</option><option value="凌晨">凌晨 0–6 点</option><option value="上午 6–9 点">上午 6–9 点</option><option value="上午 9–12 点">上午 9–12 点</option><option value="下午">下午 12–18 点</option><option value="晚上 18–21 点">晚上 18–21 点</option><option value="晚上 21–24 点">晚上 21–24 点</option>
        </select>
        <select v-model="category" aria-label="按类别筛选" @change="loadHall">
          <option value="">全部类别</option><option>羽毛球</option><option>桌游</option><option>学习组</option><option>其他</option>
        </select>
        <label class="hall-seat-filter"><input v-model="onlyHasSeats" type="checkbox" />还有名额</label>
        <button class="ghost" :disabled="hallLoading" @click="loadHall">刷新活动大厅</button>
      </div>
      <!-- G07：搜索补拉剩余分页期间给轻量提示，避免被误读成「没有结果」。 -->
      <p v-if="hallSearchBusy" class="hint" role="status">正在搜索全部活动…</p>
      <div v-if="hallLoading" class="card skeleton" aria-busy="true">
        <p>活动加载中，请稍候…</p>
        <div class="skeleton-bar"></div><div class="skeleton-bar"></div><div class="skeleton-bar short"></div>
      </div>
      <div v-if="loadError" class="card load-error">
        <p>{{ loadError }}</p>
        <button class="primary" @click="retryHall">重新加载</button>
      </div>
      <div v-if="!hallLoading && !loadError && !hallSearchIncomplete && !filteredHall.length" class="card empty-state">
        <p>{{ emptyHint }}</p>
        <!-- 任务 9（2026-11-18）：搜索 0 结果时给出按类别浏览的出路。 -->
        <p v-if="q.trim()" class="hint">没有含该词的活动，试试按类别浏览：<button class="link-btn" @click="browseCategory('羽毛球')">羽毛球</button> / <button class="link-btn" @click="browseCategory('桌游')">桌游</button> / <button class="link-btn" @click="browseCategory('学习组')">学习组</button> / <button class="link-btn" @click="browseCategory('其他')">其他</button></p>
        <div v-if="!q.trim()" class="card-cover"><img src="/img/hero.webp" alt="" /></div>
        <div v-if="searchSuggestion" class="search-suggestion">
          <p>没有完全匹配的，看看这个？</p>
          <p class="search-suggestion-title">{{ searchSuggestion.title }}</p>
          <button class="ghost" @click="openDetail(searchSuggestion.id)">查看详情</button>
        </div>
        <p v-if="q || campus || timeSlot || category">要不要自己发一个？</p>
        <button v-if="q || campus || timeSlot || category" class="primary" @click="goPublishWithQuery">去发活动</button>
        <p v-if="q" class="hint">求职、实习、竞赛组队等交流类活动请选择类别「学习组」，在标题写明关键词；小众兴趣（如健身房、音乐）请选择类别「其他」，在标题和介绍里写明关键词，方便别人搜到。</p>
        <button v-if="q" class="ghost" @click="clearSearch">看看最近的活动</button>
      </div>
      <div class="hall-grid">
        <div v-for="a in filteredHall" :key="a.id" class="card hall-card">
          <div class="card-cover hall-cover"><img :src="coverImg(a)" alt="" loading="lazy" /></div>
          <div class="card-body">
            <div class="card-head">
              <h3 class="card-title"><button type="button" class="card-title-button" @click="openDetail(a.id)">{{ a.title }} <span class="activity-no">#{{ a.id }}</span> <span v-if="isNewToday(a)" class="badge badge-accent">新发布</span> <span v-if="startsTodayUpcoming(a)" class="badge badge-accent">今天就能去</span> <span v-if="isFull(a)" class="badge badge-full">已满员</span> <span v-if="statusLabel(a)" class="badge badge-full">{{ statusLabel(a) }}</span></button></h3>
              <canvas class="cap-ring" width="112" height="112" :data-formal="a.formal_count" :data-cap="a.capacity" role="img" :aria-label="'正式 ' + a.formal_count + '/' + a.capacity + ' 人'"></canvas>
            </div>
            <p class="hall-tags">
              <span class="badge">{{ a.category }}</span><span class="badge">{{ a.location }}</span>
              <span v-if="isFull(a) && (a.reserved_count ?? 0) > 0" class="badge badge-big">已占满（正式 {{ a.formal_count }} + 预留 {{ a.reserved_count }}）</span>
              <span v-else class="badge badge-big">正式 {{ a.formal_count }}/{{ a.capacity }}</span>
              <span v-if="(a.waiting_count ?? 0) > 0" class="badge">候补 {{ a.waiting_count }} 人</span>
            </p>
            <p class="meta card-meta"><span class="nowrap">报名截止：{{ deadlineHumanPoint(a) }}</span>　<span class="nowrap">{{ deadlineCountdown(a) }}</span>　<span v-if="deadlineIsToday(a) || deadlineIsTomorrow(a)" class="badge badge-accent">{{ deadlineBadgeText(a) }}</span></p>
            <p class="meta card-meta">开始：{{ fmtWeek(a.start_time) }}<span v-if="a.end_time">–{{ fmtHM(a.end_time) }}</span>　组织者：{{ a.organizer_name }}</p>
            <p v-if="a.description" class="card-desc">{{ a.description }}</p>
            <p v-if="a.conditions" class="card-desc-cond">条件：{{ a.conditions }}</p>
            <button @click="openDetail(a.id)">{{ cardButtonText(a) }}</button>
          </div>
        </div>
      </div>
      <div v-if="hallHasMore || hallMoreError" class="card">
        <p v-if="hallMoreError" class="field-hint warn-hint" role="alert">{{ hallMoreError }}<span v-if="q.trim()">；搜索范围尚未读取完整。</span></p>
        <button class="ghost" :disabled="hallMoreBusy || hallLoading" @click="retryMoreHall">{{ hallMoreBusy ? '加载中…' : hallMoreError ? '重试加载更多活动' : '加载更多活动' }}</button>
      </div>
    </section>

    <section v-if="user && view==='detail'">
      <button class="ghost" @click="go(detailFrom)">← 返回{{ detailFrom === 'my' ? '我的活动' : '活动大厅' }}</button>
      <div v-if="detail" class="card detail-card">
        <div class="card-cover detail-cover"><img :src="coverImg(detail)" alt="" /></div>
        <div class="card-head">
          <h3>详情：{{ detail.title }} <span class="activity-no">#{{ detail.activity_id || detail.id }}</span> <span v-if="detail.category" class="badge">{{ detail.category }}</span> <span v-if="statusLabel(detail)" class="badge badge-full">{{ statusLabel(detail) }}</span></h3>
        </div>
        <!-- 2026-11-17：行动卡——状态、名额、截止倒计时与主操作收进同一区域（设计说明书 §6.4.1） -->
        <div class="signup-card">
          <div v-if="signupStateBadge(detail)" class="signup-state-row">
            <span class="badge badge-full">{{ signupStateBadge(detail) }}</span>
          </div>
          <div class="signup-cols">
            <div v-if="detailActionState !== 'terminal' && !(detail.status === 'ENDED' && (detail.my_status === 'FORMAL' || detail.my_status === 'WAITING'))" class="signup-cap">
              <canvas v-if="detail.formal !== undefined && detail.formal !== null && detail.capacity"
                class="cap-ring cap-ring-lg" width="144" height="144"
                :data-formal="detail.formal" :data-cap="detail.capacity" :data-remaining="remainingSeats(detail)"
                role="img" :aria-label="'还剩 ' + remainingSeats(detail) + ' 个名额'"></canvas>
              <div class="signup-cap-text">
                <p class="signup-cap-num">
                  <span v-if="scarceSeats(detail)" class="badge badge-accent">仅剩 {{ remainingSeats(detail) }} 个名额</span>
                  <span v-else>还剩 {{ remainingSeats(detail) }} 个名额</span>
                </p>
                <p class="signup-cap-sub">正式 {{ detail.formal ?? 0 }} / 容量 {{ detail.capacity ?? 0 }} · 候补 {{ detail.waiting ?? 0 }} 人</p>
              </div>
            </div>
            <!-- 补集：本人已参与且活动已结束，名额数字改为过去时记录行（环随之隐藏，与「还剩 X 个名额」互斥） -->
            <div v-if="detail.status === 'ENDED' && (detail.my_status === 'FORMAL' || detail.my_status === 'WAITING')" class="signup-cap-sub signup-cap-record">本次活动共 {{ detail.formal ?? 0 }} 人参加</div>
            <div class="signup-main">
              <p v-if="detailActionState !== 'terminal' && deadlineUrgency(detail) !== 'expired'" class="signup-countdown" :class="deadlineUrgency(detail)">
                <template v-if="deadlineUrgency(detail) === 'urgent'"><span class="badge badge-full">{{ deadlineCountdown(detail) }}</span><span class="nowrap">{{ deadlineHumanPoint(detail) }} 截止</span></template>
                <template v-else-if="deadlineUrgency(detail) === 'soon'">报名截止：{{ deadlineHumanPoint(detail) }} <span class="badge badge-accent">{{ deadlineBadgeText(detail) }}</span></template>
                <template v-else>{{ deadlineCountdownDetail(detail) }}</template>
              </p>

              <!-- 态 1/2/3：未报名且可报名（报名 / 加入候补；组织者报名占正式名额） -->
              <template v-if="detailActionState === 'signup'">
                <div class="signup-actions">
                  <button class="primary" :disabled="signupPending || signupBusy || resignupBusy" :aria-busy="signupPending || signupBusy || resignupBusy" @click="requestSignup(detail)">{{ signupPending ? '报名中…' : signupBusy ? '提交中…' : resignupBusy ? '正在报名…' : (joinsQueue(detail) ? '加入候补' : '报名') }}</button>
                </div>
                <p v-if="detail.roster" class="signup-hint">组织者报名将占用一个正式名额。</p>
                <p v-else-if="joinsQueue(detail)" class="signup-hint">{{ isFull(detail) ? '名额已满' : '已有候补队列，空缺按原队列顺序递补' }}，加入候补后按报名顺序排队；收到邀请后请在通知的期限内确认。</p>
                <p v-else class="signup-hint">报名后组织者仅能看到你的昵称，不会索要或公开你的联系方式。</p>
              </template>

              <!-- 态 4/5：已报名（进行中时签到行作第二操作行） -->
              <template v-else-if="detailActionState === 'formal'">
                <div class="status-card">
                  <p class="status-card-title">✓ 已报名</p>
                </div>
                <div v-if="detail.status === 'RUNNING'" class="signup-actions">
                  <p v-if="detail.my_checkin" class="signup-hint">已签到 {{ fmtWeek(detail.my_checkin.checkin_at) }}</p>
                  <button v-else class="primary" @click="doCheckin(detail)">签到</button>
                </div>
                <div v-if="detail.participation_id && !activityStarted(detail)" class="signup-actions">
                  <button class="warn" :disabled="participationLocked(detail.participation_id, detail.activity_id || detail.id)" @click="requestWithdraw(detail.participation_id, detail.activity_id || detail.id, detail.title)">退出活动</button>
                </div>
                <div v-if="acceptSuccess && String(acceptSuccess.activityId) === String(detail.activity_id || detail.id)" class="signup-actions"><button class="ghost" @click="goSignedFromAccept()">查看我报名的活动</button></div>
              </template>

              <!-- 态 6：候补中 -->
              <template v-else-if="detailActionState === 'waiting'">
                <div class="status-card status-card-waiting">
                  <p class="status-card-title">候补中<span v-if="detail.my_rank"> · 第 {{ detail.my_rank }} 名（前面还有 {{ Math.max(0, detail.my_rank - 1) }} 人）</span></p>
                </div>
                <div class="signup-actions">
                  <button v-if="detail.participation_id" class="warn" :disabled="participationLocked(detail.participation_id, detail.activity_id || detail.id)" @click="requestWithdraw(detail.participation_id, detail.activity_id || detail.id, detail.title)">放弃候补</button>
                  <button class="ghost" @click="viewMyWaiting">查看我的候补</button>
                </div>
                <p class="signup-hint">有人退出时按顺序递补，你会收到通知。</p>
              </template>

              <!-- 态 7：待确认（递补邀请；倒计时归零切「邀请已过期」） -->
              <template v-else-if="detailActionState === 'invited'">
                <div class="status-card status-card-invited">
                  <p class="status-card-title">{{ inviteSecondsLeft(detail.invitation_expires_at) === null ? '邀请已过期' : '待确认' }}</p>
                  <p v-if="inviteSecondsLeft(detail.invitation_expires_at) !== undefined && inviteSecondsLeft(detail.invitation_expires_at) !== null" class="status-card-sub">剩余 {{ inviteRemainText(detail.invitation_expires_at) }}，请在 {{ fmtWeek(detail.invitation_expires_at) }} 前确认</p>
                </div>
                <template v-if="detail.invitation_id && inviteSecondsLeft(detail.invitation_expires_at) !== null">
                  <div class="signup-actions">
                    <button class="primary" :disabled="invitationLocked(detail.invitation_id)" @click="accept(detail.invitation_id, { activityId: detail.activity_id || detail.id, title: detail.title })">接受递补</button>
                    <button class="warn" :disabled="invitationLocked(detail.invitation_id)" @click="requestReject(detail.invitation_id)">拒绝递补</button>
                  </div>
                  <p class="signup-hint">拒绝后将退出候补队列，如需再排队请重新报名。</p>
                </template>
                <p v-else-if="inviteSecondsLeft(detail.invitation_expires_at) === null" class="signup-hint">名额将顺延给下一位候补，如需参加请重新报名。</p>
              </template>

              <!-- 态 9-13：隐藏报名入口，终态句 + 看看其他活动 -->
              <template v-else-if="detailActionState === 'terminal'">
                <div class="signup-terminal">
                  <p class="signup-terminal-text">{{ signupTerminalText(detail) }}</p>
                  <button class="ghost signup-terminal-link" @click="go(detailFrom)">看看其他活动 →</button>
                </div>
              </template>
            </div>
          </div>
        </div>
        <p v-if="signupError" class="field-hint warn-hint" role="alert">{{ signupError }} <button v-if="detailActionState === 'signup'" class="ghost" :disabled="signupLocked" @click="retrySignup">重试</button></p>
        <div v-if="detailReadError || membershipNotice" class="load-error" role="status"><p>{{ detailReadError || membershipNotice.text }}</p><button class="ghost" :disabled="detailRefreshing" @click="refreshCurrentDetail(detail.activity_id || detail.id)">重新查询状态</button></div>
        <details v-if="user && detail.participation_id" :key="'history-' + detail.participation_id" class="participation-history term-help" :open="partHistory.open" @toggle="togglePartHistory">
          <summary>我的参与记录</summary>
          <p class="hint">以下为历史事件，当前状态以本页状态区为准。</p>
          <p v-if="partHistory.loading" role="status">正在读取参与记录…</p>
          <div v-else-if="partHistory.error" role="alert"><p>{{ partHistory.error }}</p><button type="button" class="ghost" @click="loadPartHistory">重试读取记录</button></div>
          <ol v-else-if="partHistory.items.length">
            <li v-for="event in partHistory.items" :key="event.id">
              <p><strong>{{ partEventTitle(event) }}</strong> · {{ fmtWeek(event.created_at) }}</p>
              <p v-if="partEventTransition(event)" class="meta">{{ partEventTransition(event) }}</p>
              <p v-if="partEventDetail(event)" class="hint">{{ partEventDetail(event) }}</p>
            </li>
          </ol>
          <p v-else-if="partHistory.loaded">暂无参与事件记录。</p>
        </details>
        <p v-if="detail.description" class="info-line"><span class="info-label">介绍</span>{{ detail.description }}</p>
        <p v-if="detail.conditions" class="info-line"><span class="info-label">条件</span>{{ detail.conditions }}</p>
        <!-- 任务 13（2026-11-20）：条件行下的通用兜底指引，不针对具体活动类型写死。 -->
        <p v-if="detail.conditions" class="hint condition-fallback">装备、水平等拿不准的，可在下方留言问组织者（仅组织者可见）。</p>
        <p class="info-line"><span class="info-label">时间</span><b><span class="nowrap">{{ fmtWeek(detail.start_time) }}</span> – <span class="nowrap">{{ fmtWeek(detail.end_time) }}</span></b><span v-if="durationText(detail)">　{{ durationText(detail) }}</span></p>
        <p class="info-line"><span class="info-label">形式</span><b>单次活动</b></p>
        <p class="info-line"><span class="info-label">地点</span><b>{{ detail.location }}</b></p>
        <p class="info-line"><span class="info-label">组织者：</span><b>{{ detail.organizer_name }}</b></p>
        <p v-if="detail.evaluation_summary && detail.evaluation_summary.count > 0" class="info-line"><span class="info-label">评价</span><b>★ {{ detail.evaluation_summary.avg_score ?? '—' }} 分 · {{ detail.evaluation_summary.count }} 人评价</b></p>
        <div v-if="user && detail.status === 'ENDED' && detail.my_attendance" class="eval-box">
          <h4>出勤与评价</h4>
          <p class="info-line"><span class="info-label">出勤</span><b>{{ attResultLabel(detail.my_attendance.result) }}<span v-if="detail.my_attendance.finalized_at">（已定版）</span><span v-else-if="detail.my_attendance.result === 'UNVERIFIED'">（待组织者核对）</span></b></p>
          <template v-if="detail.my_attendance.result === 'PRESENT'">
            <p class="info-line"><span class="info-label">评分</span>
              <button v-for="n in 5" :key="'star-' + n" class="ghost star-btn" :class="{ active: n <= evalForm.rating }" @click="evalForm.rating = n">{{ n <= evalForm.rating ? '★' : '☆' }}</button>
              <span class="hint">当前 {{ evalForm.rating }} 分</span>
            </p>
            <textarea v-model="evalForm.content" maxlength="500" rows="3" placeholder="说说这次活动的体验（可选，500 字内）"></textarea>
            <button class="primary" :disabled="evalBusy" @click="submitEvaluation(detail)">{{ evalBusy ? '提交中…' : (detail.my_evaluation ? '修改评价' : '提交评价') }}</button>
          </template>
          <p v-else class="hint">出勤结果为到场后可评价</p>
          <div v-if="detail.my_attendance.finalized_at" class="appeal-box">
            <p class="info-line"><span class="info-label">出勤申诉</span><span class="hint">出勤结果已定版，如有异议可提交申诉，管理员复核后会通知你。</span></p>
            <textarea v-model="appealForm.reason" rows="2" maxlength="2000" placeholder="说明申诉理由，如已签到却被记为缺席"></textarea>
            <button class="ghost" :disabled="appealBusy" @click="submitAttendanceAppeal(detail)">{{ appealBusy ? '提交中…' : '提交出勤申诉' }}</button>
          </div>
        </div>
        <!-- 2026-11-17：组织者管理区（仅组织者可见；公开区与参与者一致） -->
        <section v-if="detail.roster" class="organizer-zone">
          <div class="organizer-zone-head">
            <h3>组织者管理</h3>
            <span class="organizer-zone-note">仅你可见</span>
          </div>
          <div class="organizer-summary">
            <span>正式 {{ detail.formal ?? 0 }} 人</span>
            <span>候补 {{ detail.waiting ?? 0 }} 人</span>
            <span>待确认 {{ detailRosterState?.sections?.INVITED?.total ?? (detail.pending_invitations || []).length }} 人</span>
          </div>
          <OrganizerRoster :state="detailRosterState" :refreshing="detailRefreshing" :user-id="user.id" :invitations="detail.pending_invitations || []" :locked="cardActionLocked(detail.activity_id || detail.id)" @retry="loadDetailRoster" @refresh="refreshDetailRoster" @tab="type => detailRosterState.tab = type" @page="changeDetailRosterPage" @remove="row => removeMember(row, detail.activity_id || detail.id)" />
          <div v-if="detail.messages">
            <h4>收到的留言</h4>
            <div v-for="m in detail.messages" :key="'msg-' + m.id" class="message-item">
              <p><b>{{ m.sender_nickname }}</b>　<span class="nowrap">{{ fmtWeek(m.created_at) }}</span></p>
              <p>{{ m.content }}</p>
              <p v-if="m.reply" class="hint">你的回复（{{ fmtWeek(m.reply.created_at) }}）：{{ m.reply.content }}</p>
              <template v-else-if="detail.status !== 'CANCELLED'">
                <input v-model="replyDrafts[m.id]" placeholder="回一条（仅留言人可见）" maxlength="200" />
                <button class="ghost" @click="replyMessage(detail.activity_id || detail.id, m.id)">回复</button>
              </template>
            </div>
            <p v-if="!detail.messages.length" class="meta">暂无留言。</p>
          </div>
          <div v-if="detail.status === 'RUNNING'" class="checkin-box">
            <p class="info-line"><span class="info-label">签到码</span>
              <b class="checkin-code">{{ checkinCode ? checkinCode.code : '加载中…' }}</b>
              <span v-if="checkinCode" class="hint">{{ checkinSecondsLeft }} 秒后刷新</span></p>
            <p class="hint">请将签到码告知到场成员，成员在本页点「签到」输入。签到码每 5 分钟自动轮换。</p>
          </div>
          <div v-if="detail.status === 'ENDED'" class="attendance-box">
            <h4>出勤核对</h4>
            <p v-if="!attendanceList.length" class="meta">暂无出勤记录。</p>
            <div v-for="a in attendanceList" :key="'att-' + a.user_id" class="attendance-row">
              <span>{{ a.nickname }}：{{ a.checkin_at ? ('签到 ' + fmtWeek(a.checkin_at)) : '未签到' }}</span>
              <select v-model="a._result" :disabled="!!a.finalized_at">
                <option value="PRESENT">到场</option><option value="ABSENT_VERIFIED">核实缺席</option>
                <option value="EXEMPT">豁免</option><option value="UNVERIFIED">未核实</option>
              </select>
              <input v-model="a._evidence" placeholder="依据（覆盖签到/更正时必填）" :disabled="!!a.finalized_at" />
              <button class="ghost" :disabled="!!a.finalized_at || savingAttendanceId === a.user_id" @click="saveAttendance(detail.activity_id || detail.id, a)">保存</button>
              <span v-if="a.finalized_at" class="hint">已定版</span>
            </div>
            <p class="hint">核对期为活动结束后 24 小时；把有签到改判缺席、无签到改判到场或更正已有结论时必须填写依据。</p>
          </div>
          <div v-if="detail.status === 'OPEN'" class="organizer-actions">
            <button class="ghost" :disabled="deadlinePassed(detail)" @click="openActivityEditor(detail)">编辑活动</button>
            <button v-if="!deadlinePassed(detail)" class="ghost" @click="openReschedule(detail)">修改时间</button>
            <button v-else class="ghost" disabled>已过截止，不可编辑</button>
          </div>
          <ActivityEditor v-if="activityEditId && String(activityEditId) === String(detail.activity_id || detail.id)" :key="'full-' + activityEditId + '-' + token" :activity="detail" :editable="detail.status === 'OPEN' && !deadlinePassed(detail)" :session="token" :request="api" :save="saveActivityEdit" :clock="calibratedNow" @close="activityEditId = null" @saved="onActivityEdited" />
          <ActivityEditor v-if="rescheduleOpen && String(rescheduleForm.activityId) === String(detail.activity_id || detail.id)" :key="'time-' + rescheduleForm.activityId + '-' + token" :activity="detail" :editable="detail.status === 'OPEN' && !deadlinePassed(detail)" time-only :session="token" :request="api" :save="saveActivityEdit" :clock="calibratedNow" @close="rescheduleOpen = false" @saved="onActivityEdited" />
          <div v-if="detail.status !== 'CANCELLED'" class="cover-field edit-cover">
            <h4>活动封面</h4>
            <div class="cover-picker">
              <button type="button" class="cover-option" :class="{ active: editCoverChoice === 'default' }" @click="editCoverChoice = 'default'">
                <span class="cover-option-title">默认</span>
                <span class="cover-option-desc">系统按活动自动轮换封面</span>
              </button>
              <button type="button" class="cover-option" :class="{ active: editCoverChoice === 'gallery' }" @click="chooseEditGalleryCover()">
                <span class="cover-option-title">图库</span>
                <span class="cover-option-desc">从 3 张通用封面里选</span>
              </button>
              <button type="button" class="cover-option" :class="{ active: editCoverChoice === 'upload' }" @click="editCoverChoice = 'upload'">
                <span class="cover-option-title">上传</span>
                <span class="cover-option-desc">用自己的图片</span>
              </button>
            </div>
            <div v-if="editCoverChoice === 'gallery'" class="cover-thumbs">
              <button v-for="n in 3" :key="'edit-cover-g-' + n" type="button" class="cover-thumb"
                :class="{ active: editCoverGallery === '/img/cover-' + n + '.webp' }"
                @click="editCoverGallery = '/img/cover-' + n + '.webp'">
                <img :src="'/img/cover-' + n + '.webp'" alt="" loading="lazy" />
                <span>图库 {{ n }}</span>
              </button>
            </div>
            <div v-if="editCoverChoice === 'upload'" class="cover-upload">
              <input type="file" accept="image/*" @change="onEditCoverFile" />
              <span v-if="editCoverUploading" class="field-hint">上传中…</span>
            </div>
            <div class="cover-preview">
              <img :src="editSelectedCover || '/img/cover-1.webp'" alt="封面预览" />
              <span v-if="editCoverChoice === 'default'" class="field-hint">默认轮换（示例）</span>
            </div>
            <button class="primary" :disabled="editCoverBusy || editCoverUploading" @click="saveEditCover(detail.activity_id || detail.id)">{{ editCoverBusy ? '保存中…' : '保存封面' }}</button>
            <span v-if="editCoverError" class="field-hint warn-hint">{{ editCoverError }}</span>
          </div>
          <div v-if="canCancelActivity(detail)" class="organizer-danger">
            <button class="warn" :disabled="actLocked('act-' + detail.id) || cardActionLocked(detail.activity_id || detail.id)" @click="cancelActivity(detail.id)">取消活动</button>
          </div>
        </section>

        <!-- 问组织者（仅非组织者；已结束 / 已取消只读，与当日任务 2 共用同一条件分支） -->
        <div v-if="user && detail.status !== 'CANCELLED' && detail.status !== 'ENDED' && !detail.roster" class="message-box">
          <label class="field-label" for="message-draft">问组织者</label>
          <textarea id="message-draft" v-model="messageDraft" placeholder="如：请问有什么需要注意的吗？" maxlength="200" rows="3"></textarea>
          <button class="ghost" @click="sendMessage(detail.activity_id || detail.id)">发送留言</button>
          <p class="hint">留言仅组织者可见，不公开联系方式。</p>
        </div>
        <!-- 任务 4（2026-11-18）：留言加载失败不再静默显示为空。 -->
        <p v-if="myMessagesError && !detail.roster" class="field-hint warn-hint">留言加载失败，请稍后重试 <button class="ghost" @click="loadMyMessages(detail.activity_id || detail.id)">重试</button></p>
        <div v-if="myMessages.length && !detail.roster" class="my-messages">
          <h4>我发过的留言</h4>
          <div v-for="m in myMessages" :key="'mm-' + m.id" class="message-item">
            <p><span class="nowrap">{{ fmtWeek(m.created_at) }}</span></p>
            <p>{{ m.content }}</p>
            <p v-if="m.reply" class="hint">组织者回复（{{ fmtWeek(m.reply.created_at) }}）：{{ m.reply.content }}</p>
            <p v-else class="hint">组织者尚未回复</p>
          </div>
        </div>
        <details class="term-help">
          <summary>术语解释：候补 / 递补 / 预留 / 正式成员</summary>
          <p class="hint">正式成员：已占一个名额，可以参加活动。</p>
          <p class="hint">候补：名额满了，先排队；有人退出时按顺序递补。</p>
          <p class="hint">递补：有人退出空出名额时，按候补顺序邀请下一位参加。</p>
          <p class="hint">预留：已发出递补邀请、等对方确认的名额；对方确认后转为正式，过期则顺延给下一位候补。</p>
        </details>
        <div v-if="user && !detail.roster" id="report-box" class="report-box">
          <button v-if="!reportOpen" class="ghost" @click="reportOpen = true">举报</button>
          <template v-else>
            <h4>举报</h4>
            <p class="hint">当前举报对象：<b>{{ complaintTarget === 'organizer' ? ('组织者「' + (detail.organizer_name || '') + '」') : ('活动「' + detail.title + '」') }}</b></p>
            <p>
              <button class="ghost" @click="complaintTarget = complaintTarget === 'organizer' ? 'activity' : 'organizer'">改为{{ complaintTarget === 'organizer' ? '举报活动' : '举报组织者' }}</button>
            </p>
            <label class="field-label" for="complaint-category">举报类别</label>
            <select id="complaint-category" v-model="complaintForm.category">
              <option value="">请选择</option>
              <option>违规内容</option><option>人身攻击</option><option>虚假信息</option><option>其他</option>
            </select>
            <label class="field-label" for="complaint-reason">举报理由</label>
            <textarea id="complaint-reason" v-model="complaintForm.reason" rows="3" maxlength="2000" placeholder="请描述具体问题，便于管理员核实"></textarea>
            <button class="primary" :disabled="complaintBusy" @click="submitComplaint">{{ complaintBusy ? '提交中…' : '提交举报' }}</button>
            <p class="hint">举报内容仅管理员可见，请勿在公共留言中填写联系方式。</p>
            <button class="ghost" @click="reportOpen = false">收起</button>
          </template>
        </div>
      </div>
    </section>

    <section v-if="user && view==='my'">
      <div class="inline-actions">
        <button class="ghost" :disabled="myMoreBusy" @click="loadMy()">{{ myMoreBusy ? '读取中…' : '刷新我的活动' }}</button>
        <button class="ghost" :disabled="orgMoreBusy" @click="loadOrganized()">{{ orgMoreBusy ? '读取中…' : '刷新我发布的活动' }}</button>
      </div>
      <div v-if="membershipNotice" class="card" role="status"><p>{{ membershipNotice.text }}</p><button class="ghost" :disabled="myMoreBusy" @click="refreshMembership(membershipNotice.activityId)">重新查询状态</button></div>
      <div class="tabs" role="tablist">
        <button :class="{active: myTab==='signed'}" @click="myTab='signed'">已报名</button>
        <button :class="{active: myTab==='waiting'}" @click="myTab='waiting'">候补</button>
        <button :class="{active: myTab==='organized'}" @click="myTab='organized'">我发布</button>
        <button :class="{active: myTab==='history'}" @click="myTab='history'">历史</button>
      </div>
      <div v-if="myTab==='organized'">
        <div v-if="orgError" class="card load-error"><p>我发布的活动加载失败，请稍后重试</p><button class="primary" :disabled="orgMoreBusy" @click="loadOrganized(orgRetryAppend)">重试</button></div>
        <div v-for="o in organized" :key="'org-' + o.id" class="card">
          <h3 class="card-title"><button type="button" class="card-title-button" @click="openDetail(o.id)">{{ o.title }} <span class="activity-no">#{{ o.id }}</span></button></h3>
          <p>
            <span class="badge">{{ o.category }}</span><span class="badge">{{ o.location }}</span>
            <span class="badge badge-big">正式 {{ o.formal_count }}/{{ o.capacity }}</span>
            <span v-if="(o.reserved_count ?? 0) > 0" class="badge">预留 {{ o.reserved_count }}</span><span v-if="(o.waiting_count ?? 0) > 0" class="badge">候补 {{ o.waiting_count }} 人</span>
          </p>
          <p class="meta card-meta"><span class="nowrap">报名截止：{{ fmtWeek(o.deadline) }}</span>　<span class="nowrap">开始：{{ fmtWeek(o.start_time) }}<span v-if="o.end_time">–{{ fmtHM(o.end_time) }}</span></span>　状态：{{ statusLabel(o) || '报名中' }}</p>
          <button @click="openDetail(o.id)">查看详情</button>
          <button v-if="o.status !== 'CANCELLED'" @click="openRoster(o.id)">查看名单</button>
        </div>
        <p v-if="orgMoreBusy && !organized.length" class="meta" role="status">正在读取我发布的活动…</p>
        <div v-if="!organized.length && !orgError && !orgMoreBusy" class="meta"><p>暂无组织的活动。</p><button class="ghost" @click="go('publish')">去发布活动</button></div>
        <div v-if="orgHasMore" class="card"><button class="ghost" :disabled="orgMoreBusy" @click="loadMoreOrganized">{{ orgMoreBusy ? '加载中…' : '加载更多活动' }}</button></div>
      </div>
      <div v-else>
        <div v-if="myTab === 'waiting' && acceptSuccess" class="card"><h3 class="card-title">✓ 已接受递补，成为正式成员</h3><p class="meta">活动「{{ acceptSuccess.title }}」已在「已报名」中。</p><button class="ghost" @click="goSignedFromAccept()">查看我报名的活动</button></div>
        <div v-if="myTab === 'waiting' && notifInviteMissing" class="card" role="status"><h3 class="card-title">{{ notifInviteMissing.error ? '暂时无法查询这条通知的目标' : '这条邀请已处理或已失效' }}</h3><p class="meta">{{ notifInviteMissing.error ? '读取失败不代表邀请失效，请重新查询或查看原活动。' : '当前没有对应的有效邀请；旧通知不会替你接受或拒绝新的邀请。' }}</p><button v-if="notifInviteMissing.error" class="ghost" @click="viewWaitingFromNotif(notifInviteMissing.notification)">重新查询通知目标</button><button class="ghost" @click="openDetail(notifInviteMissing.activityId)">查看原活动详情</button></div>
        <div v-if="myError" class="card load-error"><p>我的活动加载失败，请稍后重试</p><button class="primary" :disabled="myMoreBusy" @click="loadMy(myRetryAppend)">重试</button></div>
        <template v-if="myTab === 'waiting'"><template v-for="grp in myWaitingGroups" :key="grp.key"><h3 v-if="grp.items.length" class="subhead">{{ grp.title }}</h3><div v-for="p in grp.items" :key="p.id" :data-part-id="p.id" tabindex="-1" :class="{ 'notif-target-card': highlightPartId === p.id }" class="card">
          <h3 class="card-title"><button type="button" class="card-title-button" @click="openDetail(p.activity_id)">{{ p.title }}</button></h3>
          <p class="meta card-meta">状态：{{ myStatusText(p) }}<span v-if="p.status === 'WAITING' && rankOf(p)">，第 {{ rankOf(p) }} 名</span>　地点：{{ p.location }}　<span class="nowrap">开始：{{ fmtWeek(p.start_time) }}<span v-if="p.end_time">–{{ fmtHM(p.end_time) }}</span></span>
            <span v-if="p.invitation_expires_at && !queueClosed(p)">　请在 <span class="nowrap">{{ fmtWeek(p.invitation_expires_at) }}</span> 前确认</span>
            <span v-if="!queueClosed(p) && p.status==='INVITED' && inviteSecondsLeft(p.invitation_expires_at) !== undefined">　<span v-if="inviteSecondsLeft(p.invitation_expires_at) !== null">剩余 {{ inviteSecondsLeft(p.invitation_expires_at) }} 秒</span><span v-else>邀请已过期</span></span>
          </p>
          <p v-if="!queueClosed(p) && p.status==='INVITED'" class="hint">拒绝后将退出候补队列，如需再排队请重新报名。</p>
          <button v-if="myTab==='history'" @click="openDetail(p.activity_id)">查看详情</button>
          <button v-if="canLeaveParticipation(p)" class="warn" :disabled="participationLocked(p.id, p.activity_id)" @click="requestWithdraw(p.id, p.activity_id, p.title)">{{ ['WAITING','INVITED'].includes(p.status) ? '放弃候补' : '退出活动' }}</button>
          <button v-if="showResignup(p)" class="primary" :disabled="resignupBusy" :aria-busy="resignupBusy" @click="resignup(p.activity_id)">{{ resignupBusy ? '正在报名…' : '重新报名' }}</button>
          <button v-if="p.invitation_id && p.status==='INVITED' && !queueClosed(p) && inviteSecondsLeft(p.invitation_expires_at) !== null" class="primary" :disabled="invitationLocked(p.invitation_id)" @click="accept(p.invitation_id, { activityId: p.activity_id, title: p.title })">接受递补</button>
          <button v-if="p.invitation_id && p.status==='INVITED' && !queueClosed(p) && inviteSecondsLeft(p.invitation_expires_at) !== null" class="warn" :disabled="invitationLocked(p.invitation_id)" @click="reject(p.invitation_id)">拒绝递补</button>
        </div></template></template>
        <div v-else v-for="p in myFiltered" :key="p.id" :data-part-id="p.id" tabindex="-1" :class="{ 'notif-target-card': highlightPartId === p.id }" class="card">
          <h3 class="card-title"><button type="button" class="card-title-button" @click="openDetail(p.activity_id)">{{ p.title }}</button></h3>
          <p class="meta card-meta">状态：{{ myStatusText(p) }}<span v-if="p.status === 'WAITING' && rankOf(p)">，第 {{ rankOf(p) }} 名</span>　地点：{{ p.location }}　<span class="nowrap">开始：{{ fmtWeek(p.start_time) }}<span v-if="p.end_time">–{{ fmtHM(p.end_time) }}</span></span>
            <span v-if="p.invitation_expires_at && !queueClosed(p)">　请在 <span class="nowrap">{{ fmtWeek(p.invitation_expires_at) }}</span> 前确认</span>
            <span v-if="!queueClosed(p) && p.status==='INVITED' && inviteSecondsLeft(p.invitation_expires_at) !== undefined">　<span v-if="inviteSecondsLeft(p.invitation_expires_at) !== null">剩余 {{ inviteSecondsLeft(p.invitation_expires_at) }} 秒</span><span v-else>邀请已过期</span></span>
          </p>
          <p v-if="!queueClosed(p) && p.status==='INVITED'" class="hint">拒绝后将退出候补队列，如需再排队请重新报名。</p>
          <button v-if="myTab==='history'" @click="openDetail(p.activity_id)">查看详情</button>
          <button v-if="canLeaveParticipation(p)" class="warn" :disabled="participationLocked(p.id, p.activity_id)" @click="requestWithdraw(p.id, p.activity_id, p.title)">{{ ['WAITING','INVITED'].includes(p.status) ? '放弃候补' : '退出活动' }}</button>
          <button v-if="showResignup(p)" class="primary" :disabled="resignupBusy" :aria-busy="resignupBusy" @click="resignup(p.activity_id)">{{ resignupBusy ? '正在报名…' : '重新报名' }}</button>
          <button v-if="p.invitation_id && p.status==='INVITED' && !queueClosed(p) && inviteSecondsLeft(p.invitation_expires_at) !== null" class="primary" :disabled="invitationLocked(p.invitation_id)" @click="accept(p.invitation_id, { activityId: p.activity_id, title: p.title })">接受递补</button>
          <button v-if="p.invitation_id && p.status==='INVITED' && !queueClosed(p) && inviteSecondsLeft(p.invitation_expires_at) !== null" class="warn" :disabled="invitationLocked(p.invitation_id)" @click="reject(p.invitation_id)">拒绝递补</button>
        </div>
        <p v-if="myMoreBusy && !myFiltered.length" class="meta" role="status">正在读取我的活动…</p>
        <p v-if="!myFiltered.length && !myError && !myMoreBusy" class="meta">{{ myEmptyText }}</p>
        <div v-if="!myFiltered.length && !myError && !myMoreBusy"><button class="ghost" @click="go('hall')">去大厅</button></div>
        <div v-if="myHasMore" class="card"><button class="ghost" :disabled="myMoreBusy" @click="loadMoreMy">{{ myMoreBusy ? '加载中…' : '加载更多活动' }}</button></div>
      </div>
      <details class="my-gov-details">
        <summary>我的信用 · 申诉 · 举报<span v-if="credit">（信用分 {{ credit.score }}）</span></summary>
        <div v-if="credit" class="card credit-card">
          <h3 class="card-title">我的信用</h3>
          <p>信用分：<b class="credit-score">{{ credit.score }}</b> <span class="meta">（初始 100 分；到场加 2 分，确认缺席扣 10 分；0–100 分）</span></p>
          <div v-if="creditEntries.length">
            <p v-for="en in creditEntries" :key="en.id" class="meta">
              {{ en.activity_title }}：{{ creditResultText(en.fact_result) }}
              <b :class="en.delta < 0 ? 'credit-down' : (en.delta > 0 ? 'credit-up' : '')">{{ en.delta > 0 ? '+' + en.delta : en.delta }}</b>
              （{{ en.score_before }} → {{ en.score_after }}）<span class="nowrap">{{ fmtWeek(en.settled_at) }}</span>
            </p>
          </div>
          <p v-else class="meta">你还没有出勤记录。出勤结果确认后会自动结算。</p>
        </div>
        <div class="my-gov-grid">
          <div class="card">
            <h3 class="card-title">我的申诉</h3>
            <p v-if="!myAppeals.length" class="meta">暂无申诉记录。</p>
            <div v-for="a in myAppeals" :key="'my-appeal-' + a.id" class="gov-row">
              <p>活动 #{{ a.activity_id ?? '—' }} <span class="badge">{{ appealStateText(a.state) }}</span></p>
              <p class="meta">提交：<span class="nowrap">{{ fmtWeek(a.submitted_at) }}</span><span v-if="a.reviewed_at">　复核：<span class="nowrap">{{ fmtWeek(a.reviewed_at) }}</span></span></p>
              <p v-if="a.reason" class="meta">理由：{{ a.reason }}</p>
            </div>
          </div>
          <div class="card">
            <h3 class="card-title">我的举报</h3>
            <p v-if="!myComplaints.length" class="meta">暂无举报记录。</p>
            <div v-for="c in myComplaints" :key="'my-complaint-' + c.id" class="gov-row">
              <p><span v-if="c.activity_title">活动「{{ c.activity_title }}」</span><span v-if="c.subject_nickname">　对象：{{ c.subject_nickname }}</span><span v-if="!c.activity_title && !c.subject_nickname">举报记录 #{{ c.id }}</span></p>
              <p class="meta"><span class="badge">{{ c.category }}</span><span class="badge">{{ complaintStateText(c.state) }}</span></p>
              <p class="meta">提交：<span class="nowrap">{{ fmtWeek(c.submitted_at) }}</span></p>
            </div>
          </div>
        </div>
      </details>
    </section>

    <section v-if="user && view==='profile'" class="card">
      <h3>个人资料</h3>
      <p class="meta">账号：{{ user.account }}</p>
      <p class="hint">昵称会展示给其他活动参与者；联系方式仅用于你本人资料，不会出现在活动详情或名单中。</p>
      <p v-if="profileLoading" class="hint" role="status">正在读取资料…</p>
      <p v-if="profileError" class="field-hint warn-hint" role="alert">{{ profileError }}</p>
      <button v-if="!profileLoading && !profileLoaded" class="ghost" type="button" @click="openProfile">重新读取资料</button>
      <form @submit.prevent="saveProfile" :aria-busy="profileLoading || profileBusy">
        <label class="field-label" for="profile-nickname">昵称（必填）</label>
        <!-- 原生 maxlength 按 UTF-16 单元截断；由 validateProfile 按接口的 Unicode 码点口径校验，保留 IME 输入。 -->
        <input id="profile-nickname" v-model="profileForm.nickname" :disabled="profileLoading || profileBusy || !profileLoaded" autocomplete="nickname" :aria-invalid="profileErrors.nickname ? 'true' : undefined" aria-describedby="profile-nickname-slot" @input="profileErrors.nickname = ''" />
        <p id="profile-nickname-slot" class="field-slot" :class="{'field-error': profileErrors.nickname}" :role="profileErrors.nickname ? 'alert' : undefined">{{ profileErrors.nickname || '1–30 字（按 Unicode 码点计）。' }}</p>
        <label class="field-label" for="profile-contact">联系方式（可选）</label>
        <input id="profile-contact" v-model="profileForm.contact" :disabled="profileLoading || profileBusy || !profileLoaded" autocomplete="tel" placeholder="手机号、邮箱等（可留空）" :aria-invalid="profileErrors.contact ? 'true' : undefined" aria-describedby="profile-contact-slot" @input="profileErrors.contact = ''" />
        <p id="profile-contact-slot" class="field-slot" :class="{'field-error': profileErrors.contact}" :role="profileErrors.contact ? 'alert' : undefined">{{ profileErrors.contact || '最多 100 字（按 Unicode 码点计）；留空可清除已保存的联系方式。' }}</p>
        <button class="primary" type="submit" :disabled="profileBusy || profileLoading || !profileLoaded">{{ profileLoading ? '读取中…' : profileBusy ? '保存中…' : '保存资料' }}</button>
      </form>
    </section>

    <section v-if="user && view==='password'" class="card">
      <h4>修改密码</h4>
      <label class="field-label" for="pw-old">原密码</label>
      <input id="pw-old" v-model="pwForm.oldPw" type="password" autocomplete="current-password" />
      <label class="field-label" for="pw-new">新密码</label>
      <input id="pw-new" v-model="pwForm.newPw" type="password" autocomplete="new-password" />
      <button class="primary" :disabled="pwBusy" @click="changePassword">{{ pwBusy ? '提交中…' : '修改密码' }}</button>
      <p class="hint">新密码须 8–64 位，且含字母与数字；修改后需要重新登录。</p>
    </section>

    <section v-if="user && view==='roster'" class="card roster-page" aria-labelledby="roster-title">
      <div class="roster-page-head">
        <div>
          <p class="roster-eyebrow">组织者管理 · 报名名单</p>
          <h2 id="roster-title">{{ rosterActivity ? rosterActivity.title : '活动名单' }}</h2>
        </div>
        <button class="ghost" @click="go('my')">← 返回我的活动</button>
      </div>
      <p v-if="rosterLoading" class="meta" role="status">正在读取名单…</p>
      <div v-if="rosterError" class="load-error" role="alert"><p>{{ rosterError }}</p><button class="ghost" :disabled="rosterLoading" @click="refreshStandaloneRoster">重新读取名单</button></div>
      <div v-if="rosterActivity && rosterActivity.roster">
        <dl class="roster-overview">
          <div><dt>活动阶段</dt><dd>{{ statusLabel(rosterActivity) || '报名中' }}</dd></div>
          <div><dt>报名截止</dt><dd>{{ fmtWeek(rosterActivity.deadline) || '—' }}</dd></div>
          <div><dt>容量</dt><dd>{{ rosterActivity.capacity ?? '—' }} 人</dd></div>
        </dl>
        <OrganizerRoster :state="rosterState" :refreshing="rosterLoading" :user-id="user.id" :invitations="rosterActivity.pending_invitations || []" :locked="cardActionLocked(rosterActivity.activity_id || rosterActivity.id)" @retry="loadStandaloneRoster" @refresh="refreshStandaloneRoster" @tab="type => rosterState.tab = type" @page="changeStandaloneRosterPage" @remove="row => removeMember(row, rosterActivity.activity_id || rosterActivity.id)" />
        <div v-if="rosterActivity.messages">
          <h4>收到的留言</h4>
          <div v-for="m in rosterActivity.messages" :key="'rm-' + m.id" class="message-item">
            <p><b>{{ m.sender_nickname }}</b>　<span class="nowrap">{{ fmtWeek(m.created_at) }}</span></p>
            <p>{{ m.content }}</p>
            <p v-if="m.reply" class="hint">你的回复（{{ fmtWeek(m.reply.created_at) }}）：{{ m.reply.content }}</p>
            <template v-else-if="rosterActivity.status !== 'CANCELLED'">
              <input v-model="replyDrafts[m.id]" placeholder="回一条（仅留言人可见）" maxlength="200" />
              <button class="ghost" @click="replyMessage(rosterActivity.activity_id || rosterActivity.id, m.id)">回复</button>
            </template>
          </div>
          <p v-if="!rosterActivity.messages.length" class="meta">暂无留言。</p>
        </div>
      </div>
    </section>

    <section v-if="user && view==='notif'">
      <button class="ghost" :disabled="notifMoreBusy" @click="loadNotif">刷新通知</button>
      <p v-if="notifs.length && groupedNotifs.length > 1" class="meta">共 {{ notifTotal }} 条通知，已折叠为 {{ groupedNotifs.length }} 组</p>
      <div class="notif-filter">
        <div class="notif-filter-left">
          <div class="notif-tabs" role="tablist" aria-label="通知筛选">
            <button role="tab" :aria-selected="notifFilter==='all'" :class="{active: notifFilter==='all'}" @click="notifFilter='all'">全部（{{ notifTotal }}）</button>
            <button role="tab" :aria-selected="notifFilter==='unread'" :class="{active: notifFilter==='unread'}" @click="notifFilter='unread'">未读（{{ unread }}）</button>
          </div>
        </div>
        <button v-if="notifs.length" class="ghost notif-readall" @click="readAll">全部标为已读</button>
      </div>
      <!-- 任务 4（2026-11-18）：通知加载失败就地提示，不弹全局红字、也不显示空态。 -->
      <div v-if="notifError" class="card load-error">
        <p>通知加载失败，请稍后重试</p>
        <button class="primary" @click="loadNotif">重试</button>
      </div>
      <div v-for="g in visibleGroups" :key="g.key" class="card notif-row notif-card" :class="{'notif-unread': groupHasUnread(g)}" @click="readOne(g.latest)">
        <div class="notif-badge-row">
          <span class="badge badge-type" :class="{'badge-type-accent': g.latest.type === '邀请'}">{{ notifTypeText(notifGroupType(g.latest)) }}</span>
          <span v-if="g.count > 1" class="notif-group-count">· 共 {{ g.count }} 条</span>
          <span class="notif-state">
            <template v-if="groupHasUnread(g)"><span class="notif-dot" aria-hidden="true"></span><span class="unread">未读</span></template>
            <span v-else class="notif-read-text">已读</span>
          </span>
        </div>
        <p class="notif-summary"><button type="button" class="notif-read-button" :aria-label="(g.latest.read_at ? '通知：' : '标为已读：') + g.latest.content" @click.stop="readOne(g.latest)">{{ g.latest.content }}</button></p>
        <p v-if="notifHasRank(g.latest)" class="meta notif-rank-note">以上名次是发这条通知时的，最新排名请点「查看当前排名」。</p>
        <div v-if="inviteCountdownText(g.latest) !== undefined" class="notif-keytime">
          <span class="cd-chip" :class="notifCdClass(g.latest)">{{ inviteCountdownText(g.latest) }}</span>
        </div>
        <p v-if="g.count > 1" class="meta notif-fold-note">同一活动 30 分钟内还有 {{ g.count - 1 }} 条同类通知，已折叠为最新一条。</p>
        <button v-if="g.count > 1" class="ghost notif-fold-toggle" @click.stop="toggleGroup(g.key)">{{ expandedGroups.has(g.key) ? '收起折叠的通知' : '展开被折叠的 ' + (g.count - 1) + ' 条' }}</button>
        <div v-if="expandedGroups.has(g.key)" class="notif-fold-list">
          <button v-for="(n, i) in g.items" :key="'fold-' + n.id" type="button" class="notif-fold-item" :aria-label="(n.read_at ? '通知：' : '标为已读：') + n.content" @click.stop="readOne(n)">
            <span v-if="!n.read_at" class="notif-dot" aria-hidden="true"></span>
            <span class="notif-fold-text">{{ notifTypeText(notifGroupType(n)) }}　第 {{ i + 1 }} 条　{{ n.content }}<span v-if="notifHasRank(n)" class="meta">（发通知时的名次）</span></span>
            <span class="notif-fold-time nowrap">{{ fmtWeek(n.created_at) }}</span>
          </button>
        </div>
        <div v-if="(notifInvitationActive(g.latest)) || (g.latest.type === '候补' && notifHasRank(g.latest)) || g.latest.activity_id != null" class="notif-action">
          <span class="notif-action-left">
            <button v-if="notifInvitationActive(g.latest)" class="primary notif-cta" @click.stop="viewWaitingFromNotif(g.latest)">查看递补</button>
            <button v-else-if="g.latest.type === '候补' && notifHasRank(g.latest)" class="ghost notif-rank-btn" @click.stop="viewWaitingFromNotif(g.latest)">查看当前排名</button>
            <button v-if="g.latest.activity_id != null" class="ghost" @click.stop="viewActivityFromNotif(g.latest)">查看活动</button>
          </span>
          <span class="meta notif-time">{{ fmtWeek(g.latest.created_at) }}</span>
        </div>
        <p v-else class="meta notif-time-only">{{ fmtWeek(g.latest.created_at) }}</p>
      </div>
      <div v-if="notifHasMore" class="card">
        <button class="ghost" :disabled="notifMoreBusy" @click="loadMoreNotif">{{ notifMoreBusy ? '加载中…' : '加载更多通知' }}</button>
      </div>
      <p v-if="notifFilter==='all' && !groupedNotifs.length && !notifError" class="meta">暂无通知。</p>
      <div v-if="notifFilter==='unread' && !visibleGroups.length && !notifError && !notifHasMore" class="notif-empty">
        <p class="meta">没有未读通知</p>
        <button class="ghost" @click="notifFilter='all'">查看全部</button>
      </div>
    </section>

    <section v-if="user && user.is_admin && view==='admin'" class="admin-page">
      <h2 class="subhead">治理工作台</h2>
      <p class="meta">待办总览与各队列；所有处理都会记入治理审计，进入本页或每次操作后自动刷新。</p>
      <p v-if="adminLoading" class="meta">加载中…</p>
      <div class="admin-grid">
        <div class="card">
          <h3>总览</h3>
          <div v-if="adminData.overview" class="overview-grid">
            <p><b>{{ adminData.overview.complaints_pending ?? 0 }}</b><span class="meta">待处理举报</span></p>
            <p><b>{{ adminData.overview.appeals_pending ?? 0 }}</b><span class="meta">待复核申诉</span></p>
            <p><b>{{ adminData.overview.recovery_pending ?? 0 }}</b><span class="meta">待审核恢复申请</span></p>
            <p><b>{{ adminData.overview.credit_reviews_pending ?? 0 }}</b><span class="meta">待处理信用审查</span></p>
            <p><b>{{ adminData.overview.bans_active ?? 0 }}</b><span class="meta">生效封禁</span></p>
            <p><b>{{ adminData.overview.bans_expired_pending ?? 0 }}</b><span class="meta">到期未解封</span></p>
            <p v-if="(adminData.overview.overdue_total ?? 0) > 0"><b>{{ adminData.overview.overdue_total }}</b><span class="badge badge-full">已逾期未处理</span></p>
          </div>
          <p v-else class="meta">暂无总览数据。</p>
        </div>

        <div class="card">
          <h3>举报队列</h3>
          <p v-if="!adminData.complaints.length" class="meta">暂无待处理举报。</p>
          <div v-for="c in adminData.complaints" :key="'ac-' + c.id" class="gov-row">
            <p><b>{{ c.applicant_nickname || ('用户 #' + (c.applicant_id ?? '')) }}</b> <span class="badge">{{ c.category }}</span> <span class="meta">对象：{{ c.activity_title ? '活动「' + c.activity_title + '」' : (c.subject_nickname ? '用户「' + c.subject_nickname + '」' : '—') }}</span></p>
            <p class="meta">{{ c.reason }}</p>
            <p class="meta"><span class="nowrap">{{ fmtWeek(c.submitted_at) }}</span></p>
            <p v-if="c.accept_deadline_at || c.handle_deadline_at" class="meta">受理截止：<span class="nowrap">{{ fmtWeek(c.accept_deadline_at) }}</span>　处理截止：<span class="nowrap">{{ fmtWeek(c.handle_deadline_at) }}</span><span v-if="c.overdue" class="badge badge-full">已逾期</span><span v-if="(c.extended_workdays ?? 0) > 0" class="badge">已延期 {{ c.extended_workdays }} 个工作日</span></p>
            <div v-if="(c.extensions || []).length" class="meta"><p v-for="ex in c.extensions" :key="'ext-COMPLAINT-' + ex.id">延期 {{ ex.extend_workdays }} 个工作日：{{ ex.reason }}（<span class="nowrap">{{ fmtWeek(ex.created_at) }}</span>）</p></div>
            <button class="ghost" @click="toggleDeadlineExt('COMPLAINT', c.id)">延期登记</button>
            <div v-if="adminExtKey === 'COMPLAINT-' + c.id" class="ban-impact">
              <label class="field-label">延期原因</label>
              <input v-model="adminExtForm.reason" maxlength="500" placeholder="必填" />
              <label class="field-label">延长工作日数</label>
              <input v-model.number="adminExtForm.days" type="number" min="1" max="30" />
              <button class="primary" :disabled="adminBusyKey === 'ext-COMPLAINT-' + c.id" @click="submitDeadlineExtension('COMPLAINT', c)">提交延期</button>
            </div>
            <select v-model="c._outcome" aria-label="处理结论">
              <option value="RESOLVED">已处理</option><option value="DISMISSED">驳回</option>
            </select>
            <input v-model="c._result" maxlength="1000" placeholder="处理结论（必填）" />
            <button class="primary" :disabled="adminBusyKey === 'complaint-' + c.id" @click="handleComplaint(c)">处理</button>
          </div>
        </div>

        <div class="card">
          <h3>申诉队列</h3>
          <p v-if="!adminData.appeals.length" class="meta">暂无待复核申诉。</p>
          <div v-for="a in adminData.appeals" :key="'aap-' + a.id" class="gov-row">
            <p><b>{{ a.applicant_nickname || ('用户 #' + (a.applicant_id ?? '')) }}</b> <span class="activity-no">决定 #{{ a.decision_id }}</span> <span class="meta">（{{ a.decision_type || '—' }}）</span></p>
            <p class="meta">{{ a.reason }}</p>
            <p class="meta"><span class="nowrap">{{ fmtWeek(a.submitted_at) }}</span></p>
            <p v-if="a.accept_deadline_at || a.handle_deadline_at" class="meta">受理截止：<span class="nowrap">{{ fmtWeek(a.accept_deadline_at) }}</span>　处理截止：<span class="nowrap">{{ fmtWeek(a.handle_deadline_at) }}</span><span v-if="a.overdue" class="badge badge-full">已逾期</span><span v-if="(a.extended_workdays ?? 0) > 0" class="badge">已延期 {{ a.extended_workdays }} 个工作日</span></p>
            <div v-if="(a.extensions || []).length" class="meta"><p v-for="ex in a.extensions" :key="'ext-APPEAL-' + ex.id">延期 {{ ex.extend_workdays }} 个工作日：{{ ex.reason }}（<span class="nowrap">{{ fmtWeek(ex.created_at) }}</span>）</p></div>
            <button class="ghost" @click="toggleDeadlineExt('APPEAL', a.id)">延期登记</button>
            <div v-if="adminExtKey === 'APPEAL-' + a.id" class="ban-impact">
              <label class="field-label">延期原因</label>
              <input v-model="adminExtForm.reason" maxlength="500" placeholder="必填" />
              <label class="field-label">延长工作日数</label>
              <input v-model.number="adminExtForm.days" type="number" min="1" max="30" />
              <button class="primary" :disabled="adminBusyKey === 'ext-APPEAL-' + a.id" @click="submitDeadlineExtension('APPEAL', a)">提交延期</button>
            </div>
            <select v-model="a._outcome" aria-label="复核结论"><option value="UPHOLD">维持原决定</option><option value="CORRECT">更正</option></select>
            <select v-if="a._outcome === 'CORRECT'" v-model="a._new_result" aria-label="更正后的出勤结果">
              <option value="PRESENT">到场</option><option value="ABSENT_VERIFIED">核实缺席</option><option value="EXEMPT">豁免</option><option value="UNVERIFIED">未核实</option>
            </select>
            <input v-model="a._result" maxlength="1000" placeholder="复核说明（可选）" />
            <button class="primary" :disabled="adminBusyKey === 'appeal-' + a.id" @click="reviewAppeal(a)">复核</button>
          </div>
        </div>

        <div class="card">
          <h3>恢复申请队列</h3>
          <div v-if="adminResetCred" class="cred-box">
            <p><b>重置凭据（仅显示一次）</b></p>
            <p>对应申请 #{{ adminResetCred.reqId }}<span v-if="adminResetCred.account">（账号 {{ adminResetCred.account }}）</span></p>
            <p class="cred-value">{{ adminResetCred.credential }}</p>
            <p class="hint">请立即线下转交申请人<span v-if="adminResetCred.expires_at">，凭据于 <span class="nowrap">{{ fmtWeek(adminResetCred.expires_at) }}</span> 前有效</span>；关闭后无法再次查看。</p>
            <button class="ghost" @click="adminResetCred = null">已转交，关闭</button>
          </div>
          <p v-if="!adminData.recovery.length" class="meta">暂无待审核恢复申请。</p>
          <div v-for="r in adminData.recovery" :key="'ar-' + r.id" class="gov-row">
            <p><b>{{ r.account }}</b>（{{ r.nickname }}） <span class="badge">{{ recoveryTypeText(r.request_type) }}</span></p>
            <p class="meta">联系方式：{{ r.contact || '—' }}</p>
            <p class="meta">{{ r.reason }}</p>
            <p class="meta"><span class="nowrap">{{ fmtWeek(r.applied_at) }}</span></p>
            <p v-if="r.accept_deadline_at || r.handle_deadline_at" class="meta">受理截止：<span class="nowrap">{{ fmtWeek(r.accept_deadline_at) }}</span>　处理截止：<span class="nowrap">{{ fmtWeek(r.handle_deadline_at) }}</span><span v-if="r.overdue" class="badge badge-full">已逾期</span><span v-if="(r.extended_workdays ?? 0) > 0" class="badge">已延期 {{ r.extended_workdays }} 个工作日</span></p>
            <div v-if="(r.extensions || []).length" class="meta"><p v-for="ex in r.extensions" :key="'ext-RECOVERY-' + ex.id">延期 {{ ex.extend_workdays }} 个工作日：{{ ex.reason }}（<span class="nowrap">{{ fmtWeek(ex.created_at) }}</span>）</p></div>
            <button class="ghost" @click="toggleDeadlineExt('RECOVERY', r.id)">延期登记</button>
            <div v-if="adminExtKey === 'RECOVERY-' + r.id" class="ban-impact">
              <label class="field-label">延期原因</label>
              <input v-model="adminExtForm.reason" maxlength="500" placeholder="必填" />
              <label class="field-label">延长工作日数</label>
              <input v-model.number="adminExtForm.days" type="number" min="1" max="30" />
              <button class="primary" :disabled="adminBusyKey === 'ext-RECOVERY-' + r.id" @click="submitDeadlineExtension('RECOVERY', r)">提交延期</button>
            </div>
            <input v-model="r._note" maxlength="500" placeholder="审核备注" />
            <button class="primary" :disabled="adminBusyKey === 'recovery-' + r.id" @click="reviewRecovery(r, 'APPROVE')">批准</button>
            <button class="warn" :disabled="adminBusyKey === 'recovery-' + r.id" @click="reviewRecovery(r, 'REJECT')">驳回</button>
          </div>
        </div>

        <div class="card">
          <h3>信用审查队列</h3>
          <p v-if="!adminData.creditReviews.length" class="meta">暂无待处理信用审查。</p>
          <div v-for="cr in adminData.creditReviews" :key="'cr-' + cr.id" class="gov-row">
            <p><b>{{ cr.nickname || ('用户 #' + (cr.user_id ?? '')) }}</b> <span class="badge">30 日缺席 {{ cr.absence_count ?? '—' }} 次</span></p>
            <p class="meta">窗口：<span class="nowrap">{{ fmtWeek(cr.window_start) }}</span> – <span class="nowrap">{{ fmtWeek(cr.window_end) }}</span></p>
            <p v-if="cr.accept_deadline_at || cr.handle_deadline_at" class="meta">受理截止：<span class="nowrap">{{ fmtWeek(cr.accept_deadline_at) }}</span>　处理截止：<span class="nowrap">{{ fmtWeek(cr.handle_deadline_at) }}</span><span v-if="cr.overdue" class="badge badge-full">已逾期</span><span v-if="(cr.extended_workdays ?? 0) > 0" class="badge">已延期 {{ cr.extended_workdays }} 个工作日</span></p>
            <div v-if="(cr.extensions || []).length" class="meta"><p v-for="ex in cr.extensions" :key="'ext-CREDIT_REVIEW-' + ex.id">延期 {{ ex.extend_workdays }} 个工作日：{{ ex.reason }}（<span class="nowrap">{{ fmtWeek(ex.created_at) }}</span>）</p></div>
            <button class="ghost" @click="toggleDeadlineExt('CREDIT_REVIEW', cr.id)">延期登记</button>
            <div v-if="adminExtKey === 'CREDIT_REVIEW-' + cr.id" class="ban-impact">
              <label class="field-label">延期原因</label>
              <input v-model="adminExtForm.reason" maxlength="500" placeholder="必填" />
              <label class="field-label">延长工作日数</label>
              <input v-model.number="adminExtForm.days" type="number" min="1" max="30" />
              <button class="primary" :disabled="adminBusyKey === 'ext-CREDIT_REVIEW-' + cr.id" @click="submitDeadlineExtension('CREDIT_REVIEW', cr)">提交延期</button>
            </div>
            <button class="ghost" :disabled="adminBusyKey === 'credit-' + cr.id" @click="handleCreditReview(cr, 'REVIEWED')">已审查</button>
            <button class="warn" :disabled="adminBusyKey === 'credit-' + cr.id" @click="handleCreditReview(cr, 'DISMISSED')">忽略</button>
          </div>
        </div>

        <div class="card">
          <h3>封禁管理</h3>
          <div class="dt-row">
            <input v-model="adminUserQuery" placeholder="按账号或昵称搜索用户" @keyup.enter="loadAdminUsers" />
            <button class="ghost" @click="loadAdminUsers">搜索</button>
          </div>
          <p v-if="!adminData.users.length" class="meta">没有匹配的用户。</p>
          <div v-for="u in adminData.users" :key="'au-' + u.id" class="gov-row">
            <p><b>{{ u.account }}</b>（{{ u.nickname }}） <span class="badge">信用 {{ u.credit_score ?? '—' }}</span><span v-if="u.is_admin" class="badge">管理员</span><span v-if="u.banned" class="badge badge-full">已封禁</span> <span class="meta">#{{ u.id }}</span></p>
            <button v-if="!u.banned" class="warn" @click="openBanImpact(u)">{{ adminBanTarget === u.id ? '收起封禁表单' : '封禁' }}</button>
            <div v-if="adminBanTarget === u.id" class="ban-impact">
              <p v-if="adminBanImpactBusy" class="meta">正在加载影响范围…</p>
              <template v-else-if="adminBanImpact">
                <p class="meta">候补 {{ (adminBanImpact.waiting || []).length }} 项<span v-if="impactTitles(adminBanImpact.waiting)">：{{ impactTitles(adminBanImpact.waiting) }}</span></p>
                <p class="meta">待确认邀请 {{ (adminBanImpact.invited || []).length }} 项<span v-if="impactTitles(adminBanImpact.invited)">：{{ impactTitles(adminBanImpact.invited) }}</span></p>
                <p class="meta">未来正式报名 {{ (adminBanImpact.future_formal || []).length }} 项<span v-if="impactTitles(adminBanImpact.future_formal)">：{{ impactTitles(adminBanImpact.future_formal) }}</span></p>
                <p class="meta">进行中正式报名 {{ (adminBanImpact.running_formal || []).length }} 项<span v-if="impactTitles(adminBanImpact.running_formal)">：{{ impactTitles(adminBanImpact.running_formal) }}</span></p>
                <p class="meta">进行中的组队活动 {{ (adminBanImpact.organized_active || []).length }} 项<span v-if="impactTitles(adminBanImpact.organized_active)">：{{ impactTitles(adminBanImpact.organized_active) }}</span></p>
                <label class="field-label" for="ban-days">封禁天数（1–30）</label>
                <input id="ban-days" v-model.number="adminBanForm.days" type="number" min="1" max="30" />
                <label class="field-label" for="ban-reason">封禁原因</label>
                <input id="ban-reason" v-model="adminBanForm.reason" maxlength="500" placeholder="必填" />
                <label class="field-label" for="ban-future">未来活动</label>
                <select id="ban-future" v-model="adminBanForm.future_formal"><option value="REMOVE">移出（默认）</option><option value="KEEP">保留</option></select>
                <label class="field-label" for="ban-organized">进行中的组织活动</label>
                <select id="ban-organized" v-model="adminBanForm.organized"><option value="CANCEL">取消（默认）</option><option value="KEEP">保留</option></select>
                <button class="warn" :disabled="adminBusyKey === 'ban-' + u.id" @click="banUser(u)">确认封禁</button>
              </template>
            </div>
          </div>
          <h4>封禁记录</h4>
          <p v-if="!adminData.bans.length" class="meta">暂无封禁记录。</p>
          <div v-for="b in adminData.bans" :key="'ab-' + b.user_id + '-' + b.banned_at" class="gov-row">
            <p><b>{{ b.account }}</b>（{{ b.nickname }}） <span v-if="b.expired" class="badge">已过期</span><span v-if="b.lifted_at" class="badge">已解封</span><span v-else class="badge badge-full">生效中</span></p>
            <p class="meta">原因：{{ b.reason }}　起：<span class="nowrap">{{ fmtWeek(b.banned_at) }}</span>　止：<span class="nowrap">{{ fmtWeek(b.expires_at) }}</span></p>
            <p v-if="b.review_deadline_at" class="meta">复核截止：<span class="nowrap">{{ fmtWeek(b.review_deadline_at) }}</span><span v-if="b.overdue" class="badge badge-full">已逾期</span></p>
            <template v-if="!b.lifted_at">
              <input v-model="b._reason" maxlength="500" placeholder="解封原因" />
              <button class="ghost" :disabled="adminBusyKey === 'unban-' + b.user_id" @click="unbanUser(b)">解封</button>
            </template>
            <p v-else class="meta">已于 <span class="nowrap">{{ fmtWeek(b.lifted_at) }}</span> 解封</p>
          </div>
        </div>

        <div class="card">
          <h3>活动治理</h3>
          <p v-if="!adminData.activities.length" class="meta">暂无活动。</p>
          <div v-for="a in adminData.activities" :key="'ag-' + a.id" class="gov-row">
            <p><b>{{ a.title }}</b> <span class="activity-no">#{{ a.id }}</span> <span class="badge">{{ a.status }}</span><span v-if="a.delisted" class="badge badge-full">已下架</span></p>
            <p class="meta"><span class="nowrap">{{ fmtWeek(a.start_time) }}</span>　组织者：{{ a.organizer_name || '—' }}</p>
            <input v-model="a._reason" maxlength="500" :placeholder="a.delisted ? '恢复展示原因' : '下架原因'" />
            <button v-if="!a.delisted" class="warn" :disabled="adminBusyKey === 'act-' + a.id" @click="delistActivity(a)">下架</button>
            <button v-else class="ghost" :disabled="adminBusyKey === 'act-' + a.id" @click="relistActivity(a)">恢复展示</button>
            <button class="ghost" @click="toggleAdminAttendance(a)">{{ adminAttOpenId === a.id ? '收起出勤' : '出勤' }}</button>
            <!-- DG-ADM-01（2026-11-20）：出勤名单只读展示；组织者本人一行由管理员核对（SDD §6.9）。 -->
            <div v-if="adminAttOpenId === a.id" class="attendance-box">
              <p v-if="adminAttLoading" class="meta">出勤名单加载中…</p>
              <p v-else-if="adminAttError" class="meta">{{ adminAttError }}</p>
              <template v-else>
                <p v-if="!adminAttRows.length" class="meta">暂无出勤记录。</p>
                <template v-for="r in adminAttRows" :key="'aat-' + (r.id ?? r.user_id)">
                  <div class="attendance-row">
                    <span><b>{{ r.nickname || ('用户 #' + (r.user_id ?? '—')) }}</b></span>
                    <span v-if="isAdminOrganizerRow(a, r)" class="badge">组织者本人 · 由管理员核对</span>
                    <span class="meta">出勤：{{ adminAttResultText(r) }}</span>
                    <span v-if="adminAttCheckinAt(r)" class="meta">签到 <span class="nowrap">{{ fmtWeek(adminAttCheckinAt(r)) }}</span></span>
                    <span class="meta">版本 {{ r.version ?? '—' }}</span>
                    <span class="badge">{{ r.finalized_at ? '已定版' : '未定版' }}</span>
                    <template v-if="isAdminOrganizerRow(a, r) && !r.finalized_at">
                      <select v-model="r._result" aria-label="组织者出勤结果">
                        <option value="PRESENT">到场</option><option value="ABSENT_VERIFIED">核实缺席</option>
                        <option value="EXEMPT">豁免</option><option value="UNVERIFIED">未核实</option>
                      </select>
                      <input v-model="r._evidence" maxlength="500" placeholder="核对依据" />
                      <button class="primary" :disabled="adminBusyKey === 'admin-att-org-' + a.id" @click="submitOrganizerAttendance(a)">管理员核对</button>
                    </template>
                  </div>
                  <p v-if="isAdminOrganizerRow(a, r) && r.finalized_at" class="meta">组织者出勤已定版，更正请走申诉复核</p>
                </template>
                <p v-if="adminAttRows.length && !adminAttRows.some(r => isAdminOrganizerRow(a, r))" class="meta">名单中未找到组织者本人的出勤记录。</p>
                <p class="hint">非组织者成员的出勤更正由组织者核对或申诉复核处理，此处只核对组织者本人。</p>
              </template>
            </div>
          </div>
        </div>

        <div class="card">
          <h3>管理员</h3>
          <p v-if="!adminData.admins.length" class="meta">暂无管理员记录。</p>
          <div v-for="ad in adminData.admins" :key="'adm-' + ad.user_id" class="gov-row">
            <p><b>{{ ad.account }}</b>（{{ ad.nickname }}） <span class="badge">{{ ad.enabled ? '启用' : '已停用' }}</span> <span class="meta">#{{ ad.user_id }}</span></p>
            <button v-if="ad.enabled" class="warn" @click="revokeAdmin(ad)">撤销</button>
          </div>
          <h4>任命管理员</h4>
          <input v-model="adminAppointForm.user_id" placeholder="用户 ID" />
          <input v-model="adminAppointForm.note" maxlength="500" placeholder="备注（可选）" />
          <button class="ghost" @click="appointAdmin">任命</button>
        </div>

        <div class="card">
          <h3>治理审计</h3>
          <p v-if="!adminData.actions.length" class="meta">暂无审计记录。</p>
          <div v-for="ac in adminData.actions" :key="'act-' + ac.id" class="gov-row">
            <p><span class="nowrap">{{ fmtWeek(ac.created_at) }}</span>　<b>{{ adminActionText(ac.action) }}</b></p>
            <p class="meta">对象：{{ ac.target_type || '—' }} #{{ ac.target_id ?? '—' }}<span v-if="ac.reason">　理由：{{ ac.reason }}</span></p>
          </div>
        </div>
      </div>
    </section>

    <section v-if="user && view==='publish'" class="card publish-form">
      <h3>发布活动</h3>
      <label>标题（必填） <input id="publish-title" v-model="form.title" :aria-invalid="!!publishErrors.title" :aria-describedby="publishErrors.title ? 'publish-title-error' : undefined" placeholder="如：羽毛球友谊赛" @input="publishErrors.title = ''" /><span class="field-hint">必填，最多 50 字</span><span id="publish-title-error" v-if="publishErrors.title" class="field-hint warn-hint" role="alert">{{ publishErrors.title }}</span><span v-if="titleWeekdayHint" class="field-hint warn-hint">{{ titleWeekdayHint }}</span></label>
      <!-- 任务 18（2026-11-20）：封面选择上移到标题下方，发布前第一眼可见；三选一逻辑不变。 -->
      <div class="cover-field">
        <span class="field-label">活动封面</span>
        <div class="cover-picker">
          <button type="button" class="cover-option" :class="{ active: coverChoice === 'default' }" @click="coverChoice = 'default'">
            <span class="cover-option-title">默认</span>
            <span class="cover-option-desc">系统按活动自动轮换封面</span>
          </button>
          <button type="button" class="cover-option" :class="{ active: coverChoice === 'gallery' }" @click="chooseGalleryCover()">
            <span class="cover-option-title">图库</span>
            <span class="cover-option-desc">从 3 张通用封面里选</span>
          </button>
          <button type="button" class="cover-option" :class="{ active: coverChoice === 'upload' }" @click="coverChoice = 'upload'">
            <span class="cover-option-title">上传</span>
            <span class="cover-option-desc">用自己的图片</span>
          </button>
        </div>
        <div v-if="coverChoice === 'gallery'" class="cover-thumbs">
          <button v-for="n in 3" :key="'cover-g-' + n" type="button" class="cover-thumb"
            :class="{ active: coverGallery === '/img/cover-' + n + '.webp' }"
            @click="coverGallery = '/img/cover-' + n + '.webp'">
            <img :src="'/img/cover-' + n + '.webp'" alt="" loading="lazy" />
            <span>图库 {{ n }}</span>
          </button>
        </div>
        <div v-if="coverChoice === 'upload'" class="cover-upload">
          <input type="file" accept="image/*" @change="onPublishCoverFile" />
          <span v-if="coverUploading" class="field-hint">上传中…</span>
          <span v-if="coverUploadError" class="field-hint warn-hint">{{ coverUploadError }}</span>
        </div>
        <div class="cover-preview">
          <img :src="selectedCover || '/img/cover-1.webp'" alt="封面预览" />
          <span v-if="coverChoice === 'default'" class="field-hint">默认轮换（示例）</span>
        </div>
      </div>
      <label>类别（必填）
        <select id="publish-category" v-model="form.category" :aria-invalid="!!publishErrors.category" :aria-describedby="publishErrors.category ? 'publish-category-error' : undefined" @change="publishErrors.category = ''"><option value="">请选择</option><option>羽毛球</option><option>桌游</option><option>学习组</option><option>其他</option></select>
        <span class="field-hint">必填</span>
        <span id="publish-category-error" v-if="publishErrors.category" class="field-hint warn-hint" role="alert">{{ publishErrors.category }}</span>
        <span v-if="form.category === '其他'" class="field-hint">「其他」类活动：请在标题和介绍里写明关键词，方便别人搜到；转让类请写清人数、时间、价格；招募类请写清招募对象、固定训练时间与选拔方式；运动/兴趣约人请写清场地、水平要求、新手是否友好、有无器材可借；拼单/费用类请把费用与截单时间写进介绍第一行</span>
        <span v-if="form.category === '学习组'" class="field-hint">学习 / 读书类活动：请在介绍里写明书目或学习内容、讨论频率、是否定期</span>
      </label>
      <label>地点 <input id="publish-location" v-model="form.location" :aria-invalid="!!publishErrors.location" :aria-describedby="publishErrors.location ? 'publish-location-error' : undefined" placeholder="如：江安校区体育馆三楼，提前 10 分钟在一楼大厅集合；拼车请写清出发地和目的地，如：春熙路出发 → 江安校区南门" @input="publishErrors.location = ''" /></label><span class="field-hint">必填，最多 100 字；先写校区，再写场馆与楼层、集合点</span><span id="publish-location-error" v-if="publishErrors.location" class="field-hint warn-hint" role="alert">{{ publishErrors.location }}</span><details class="field-examples"><summary>查看例子</summary><p class="field-hint">请先写校区（望江/华西/江安/其他），再写场馆与楼层；如有电梯/坡道请写明，如：江安校区体育馆三楼，有电梯。拼车请写清出发地和目的地，如：市中心春熙路出发 → 江安校区南门。拼单请写取餐点，如：江安校区六舍楼下取餐点。球场等多片场地的请写清场地号与集合点，如：江安校区体育馆三楼 3 号场门口集合。</p></details>
      <label>人数上限 <input id="publish-capacity" v-model.number="form.capacity" :aria-invalid="!!publishErrors.capacity" :aria-describedby="publishErrors.capacity ? 'publish-capacity-error' : undefined" type="number" min="1" max="100" @input="publishErrors.capacity = ''" /><span class="field-hint">范围 1–100 人；请按实际需要改人数，默认 4 人（含组织者自己）</span><span id="publish-capacity-error" v-if="publishErrors.capacity" class="field-hint warn-hint" role="alert">{{ publishErrors.capacity }}</span></label>
      <label class="field-label" for="publish-deadline">报名截止（必填）</label>
      <div class="dt-row"><input id="publish-deadline" v-model="form.deadline" :aria-invalid="!!dtErrors.deadline" :aria-describedby="dtErrors.deadline ? 'publish-deadline-error' : undefined" :placeholder="'如：' + todayStr + ' 21:00'" @blur="onDTBlur('deadline')" @input="onDTInput('deadline')" /><button class="ghost picker-btn" type="button" @click="openPicker('form','deadline')">📅 选择</button></div>
      <span id="publish-deadline-error" v-if="dtErrors.deadline" class="field-hint warn-hint" role="alert">{{ dtErrors.deadline }}</span>
      <span class="field-hint">点「📅 选择」打开日历，或直接按「年-月-日 时:分」输入（24 小时制）。</span>
      <span v-if="form.deadline && !dtErrors.deadline" class="field-hint">已选：{{ fmtWeek(form.deadline.replace('T', ' ')) }}</span>
      <span class="field-hint">截止须早于开始，建议提前 24 小时；临时活动可填在开始前不久，适合临时约饭。</span>
      <label class="field-label" for="publish-start_time">开始时间（必填）</label>
      <div class="dt-row"><input id="publish-start_time" v-model="form.start_time" :aria-invalid="!!dtErrors.start_time" :aria-describedby="dtErrors.start_time ? 'publish-start_time-error' : undefined" :placeholder="'如：' + tomorrowStr + ' 10:00'" @blur="onDTBlur('start_time')" @input="onDTInput('start_time')" /><button class="ghost picker-btn" type="button" @click="openPicker('form','start_time')">📅 选择</button></div>
      <span id="publish-start_time-error" v-if="dtErrors.start_time" class="field-hint warn-hint" role="alert">{{ dtErrors.start_time }}</span>
      <span class="field-hint">点「📅 选择」打开日历，或直接按「年-月-日 时:分」输入（24 小时制）。</span>
      <span v-if="form.start_time && !dtErrors.start_time" class="field-hint">已选：{{ fmtWeek(form.start_time.replace('T', ' ')) }}</span>
      <label class="field-label" for="publish-end_time">结束时间（必填）</label>
      <div class="dt-row"><input id="publish-end_time" v-model="form.end_time" :aria-invalid="!!dtErrors.end_time" :aria-describedby="dtErrors.end_time ? 'publish-end_time-error' : undefined" :placeholder="'如：' + tomorrowStr + ' 12:00'" @blur="onDTBlur('end_time')" @input="onDTInput('end_time')" /><button class="ghost picker-btn" type="button" @click="openPicker('form','end_time')">📅 选择</button></div>
      <span id="publish-end_time-error" v-if="dtErrors.end_time" class="field-hint warn-hint" role="alert">{{ dtErrors.end_time }}</span>
      <span class="field-hint">点「📅 选择」打开日历，或直接按「年-月-日 时:分」输入（24 小时制）。</span>
      <span v-if="form.end_time && !dtErrors.end_time" class="field-hint">已选：{{ fmtWeek(form.end_time.replace('T', ' ')) }}</span>
      <label>介绍 <textarea id="publish-description" v-model="form.description" :aria-invalid="!!publishErrors.description" :aria-describedby="publishErrors.description ? 'publish-description-error' : undefined" rows="3" @input="publishErrors.description = ''" placeholder="如：一起自习，互相监督、互不打扰；活动均为单次，想找固定搭子请写明频率，如：每周三晚固定；轮换玩法请写明本期玩什么，如：本周玩《长夜将明》"></textarea><span class="field-hint">选填，最多 2000 字</span><span id="publish-description-error" v-if="publishErrors.description" class="field-hint warn-hint" role="alert">{{ publishErrors.description }}</span><span class="field-hint warn-hint">介绍是公开的，请勿填写微信号、手机号等联系方式</span></label>
      <label>参与条件 <textarea id="publish-conditions" v-model="form.conditions" :aria-invalid="!!publishErrors.conditions" :aria-describedby="publishErrors.conditions ? 'publish-conditions-error' : undefined" rows="3" @input="publishErrors.conditions = ''" placeholder="如：水平不限，免费参加；没有球拍可提前说一声；新手友好，有人带，主持人会先教规则，零基础可来；费用请写明，如：AA 场地费 10 元；招募队友请写明水平、每周投入与合作期限，如：招募建模队友，要求会 Python，每周投入 8 小时以上，合作到国赛结束；夜间活动请写明灯光与结伴情况，如：全程路灯明亮，请穿亮色衣服"></textarea><span class="field-hint">选填，最多 500 字</span><span id="publish-conditions-error" v-if="publishErrors.conditions" class="field-hint warn-hint" role="alert">{{ publishErrors.conditions }}</span><span class="field-hint warn-hint">参与条件是公开的，请勿填写微信号、手机号等联系方式</span></label>
      <button class="primary" :disabled="publishBusy" @click="publish">{{ publishBusy ? '提交中…' : '发布' }}</button>
    </section>
    <footer v-if="user && demoMode" class="page-foot">
      <button class="danger" @click="resetDemo">⚠ 恢复演示数据</button>
      <span class="hint">危险操作：会清空当前业务数据并恢复种子数据，仅演示时使用。</span>
      <button class="ghost" @click="exitDemoMode">退出演示模式</button>
    </footer>
    <div v-if="picker" class="picker-backdrop" @click.self="picker = null">
      <div class="picker-pop" role="dialog" aria-label="选择日期时间">
        <h4>{{ pickerTitle }}</h4>
        <div class="picker-nav">
          <button class="ghost" @click="pickerPrevMonth">‹ 上月</button>
          <span class="picker-month">{{ pickerYear }} 年 {{ pickerMonth }} 月</span>
          <button class="ghost" @click="pickerNextMonth">下月 ›</button>
        </div>
        <div class="picker-grid">
          <span v-for="w in ['日','一','二','三','四','五','六']" :key="'w'+w" class="picker-week">{{ w }}</span>
          <span v-for="b in pickerBlanks" :key="'b'+b"></span>
          <button v-for="d in pickerDays" :key="'d'+d" :class="{active: d === pickerDay}" @click="pickerDay = d">{{ d }}</button>
        </div>
        <div class="picker-time">
          <label>时间 <select v-model.number="pickerHour" aria-label="小时"><option v-for="h in 24" :key="'h'+h" :value="h-1">{{ String(h-1).padStart(2,'0') }}</option></select> : <select v-model.number="pickerMinute" aria-label="分钟"><option v-for="m in 60" :key="'m'+m" :value="m-1">{{ String(m-1).padStart(2,'0') }}</option></select></label>
        </div>
        <p class="meta">已选：{{ pickerDisplay }}</p>
        <p class="hint">默认取当前时间后 1 小时，点日期或时间可改。</p>
        <button class="primary" @click="confirmPicker">确定</button>
        <button class="ghost" @click="picker = null">取消</button>
      </div>
    </div>
    <div v-if="authModal.visible" class="auth-modal-backdrop" @click.self="closeAuthModal()">
      <div ref="authModalCard" class="auth-modal-card" role="dialog" aria-modal="true" :aria-label="authModal.title">
        <p class="auth-modal-tag">{{ authModal.title }}</p>
        <p class="auth-modal-text">{{ authModal.text }}</p>
        <div v-if="authModal.input" class="message-box">
          <label class="field-label" for="confirm-note">{{ authModal.input.label }}</label>
          <textarea id="confirm-note" v-model="authModal.input.value" rows="2" :aria-required="!!authModal.input.required" :aria-invalid="!!authModalInputError" aria-describedby="confirm-note-hint"></textarea>
          <p id="confirm-note-hint" class="field-hint" :class="{ 'warn-hint': authModalInputError }" :role="authModalInputError ? 'alert' : undefined">{{ authModalInputError || ('最多 ' + authModal.input.maxLength + ' 字') }}</p>
        </div>
        <div v-if="authModal.onConfirm" class="auth-modal-actions">
          <button ref="authModalCancelBtn" type="button" class="ghost" @click="closeAuthModal()">{{ authModal.cancelLabel || '取消' }}</button>
          <button ref="authModalConfirmBtn" type="button" class="primary" :disabled="!!authModalInputError" @click="confirmAuthModal()">{{ authModal.confirmLabel || '确认' }}</button>
        </div>
        <button v-else ref="authModalBtn" type="button" class="primary auth-primary" @click="closeAuthModal()">知道了</button>
      </div>
    </div>
    <footer class="app-footer"><span>找个搭子 v{{ APP_VERSION }}</span><template v-if="SHOW_ICP"><span class="foot-sep">·</span><a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener">蜀ICP备2026072554号-1</a></template></footer>
  </main>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { Eye, EyeOff } from 'lucide-vue-next'
import ActivityEditor from './components/ActivityEditor.vue'
import OrganizerRoster from './components/OrganizerRoster.vue'
// 应用版本号：与 backend/pom.xml、frontend/package.json 三处同步维护（规则见仓库根 CHANGELOG.md）。
const APP_VERSION = '1.1.0'
// ICP 备案号只在已备案的腾讯云域名/IP 上悬挂；微软云（海外）等其他入口不显示
const SHOW_ICP = ['tangyuxiang.xyz', 'www.tangyuxiang.xyz', '43.143.97.80'].includes(window.location.hostname)
const view = ref('hall')
// 详情页从哪来（大厅 / 我的活动），返回时回到原地（2026-11-10 详情独立页）。
const detailFrom = ref('hall')
const menuOpen = ref(false)
// 顶栏用户菜单（昵称按钮 + 下拉）：本轮不做点外关闭，Esc 关闭并交还焦点。
const userMenuOpen = ref(false)
const userMenuBtn = ref(null)
const userMenu = ref(null)
// 2026-11-17：移动端抽屉的菜单钮与抽屉节点（仅呈现层引用）。
const menuBtn = ref(null), mobileNav = ref(null)
let drawerMq = null
const myTab = ref('signed')
const hallLoading = ref(false)
const loadError = ref('')
// 任务 4（2026-11-18）：失败状态分层呈现——后台拉取失败就地提示，不弹全局红字。
const notifError = ref('')
const myError = ref('')
const orgError = ref('')
const myMessagesError = ref('')
const signupError = ref('')
const detailReadError = ref(''), detailRefreshing = ref(false)
// OBS-5：本人参与事件流按需读取，默认不请求；切换活动/会话即作废。
const partHistory = ref({ pid: null, open: false, loading: false, error: '', loaded: false, items: [] })
let partHistorySeq = 0
const membershipNotice = ref(null)
let navigationSeq = 0, queueRefreshAt = 0
const acknowledgedConditions = new Map()
const loginBusy = ref(false)
const registerBusy = ref(false)
const signupBusy = ref(false)
const actionBusy = ref(new Set())
function actLocked(k) { return actionBusy.value.has(k) }
function actLock(k) { actionBusy.value = new Set(actionBusy.value).add(k) }
function actUnlock(k) {
  const next = new Set(actionBusy.value)
  next.delete(k)
  actionBusy.value = next
}
function cardActionLocked(aid) { return aid != null && actLocked('member-' + aid) }
function participationLocked(pid, aid) { return actLocked('part-' + pid) || cardActionLocked(aid) }
function invitationActivityId(id) {
  if (detail.value && String(detail.value.invitation_id) === String(id)) return detail.value.activity_id || detail.value.id
  return mine.value.find(p => String(p.invitation_id) === String(id))?.activity_id
}
function invitationLocked(id) { return actLocked('inv-' + id) || cardActionLocked(invitationActivityId(id)) }
function lockActionKeys(keys) {
  const distinct = [...new Set(keys)]
  if (distinct.some(actLocked)) return null
  const sessionToken = token.value
  distinct.forEach(actLock)
  return () => { if (token.value === sessionToken) distinct.forEach(actUnlock) }
}
// 2026-11-20 任务 1：报名类操作的即时加载态。signupPending 独立于 signupBusy，
// 避免 requestSignup 置位后被 signup() 开头的 signupBusy 守卫拦住；resignupBusy
// 管提示条/「我的活动」的重新报名；signupLocked 统一给提示条按钮做防重复点击。
const signupPending = ref(false)
const resignupBusy = ref(false)
const signupLocked = computed(() => signupPending.value || signupBusy.value || resignupBusy.value)
// 2026-11-20 任务 2：「还有名额」开关（纯前端过滤，默认关）。
const onlyHasSeats = ref(false)
const publishBusy = ref(false)
const user = ref(null)
const token = ref(localStorage.getItem('token') || '')
const account = ref(''), password = ref(''), nickname = ref('')
const msg = ref('')
// 2026-11-19 靶子 B：接受递补成功后横幅内嵌的入口（只由 accept() 成功分支设置）。
const msgAction = ref(null) // { text, label, run }
const acceptSuccess = ref(null)
// G19（2026-11-20）：通知目标跳转链的本地呈现状态——待高亮的参与记录 id 与邀请失效提示。
const highlightPartId = ref(null)
const notifInviteMissing = ref(null) // { activityId }
function goSignedFromAccept() { acceptSuccess.value = null; myTab.value = 'signed'; go('my') }
// 任务 3（2026-11-15）：登录失败时在报错下方给出注册引导（通用一句，不区分账号是否存在）。
const loginHint = ref(false)
// 2026-11-17：注册独立页与登录/注册反馈浮层（呈现层状态，不改业务逻辑）。
const regErrors = ref({ account: '', nickname: '' })
const loginErrors = ref({ account: '', password: '' })
const showPwdLogin = ref(false), showPwdReg = ref(false)
const authReturn = ref(null)
const regPwdServerError = ref('')
const passwordConfirm = ref('')
const regConfirmError = ref('')
const authModal = ref({ visible: false, title: '提示', text: '', focusAfter: null, confirmLabel: '', cancelLabel: '', onConfirm: null, onClose: null })
const authModalBtn = ref(null)
const authModalCancelBtn = ref(null)
const authModalCard = ref(null)
const authModalConfirmBtn = ref(null)
// 打开浮层前记录触发元素，关闭时（无 focusAfter 的路径）把焦点还回去。
let authModalTrigger = null
const hall = ref([]), detail = ref(null), mine = ref([]), organized = ref([]), notifs = ref([]), unread = ref(0)
// 任务 6（2026-11-19）：通知总条数（后端 /notifications 的 total），页签与顶部计数统一用它。
const notifTotal = ref(0)
// 阶段三 CEM-10（2026-11-15）：我的信用（信用分 + 流水，GET /me/credit）。
const credit = ref(null), creditEntries = ref([])
// 阶段四 CEM-09（2026-11-15）：举报 / 出勤申诉 / 账号恢复 / 治理工作台。
const complaintForm = ref({ category: '', reason: '' })
const complaintTarget = ref('activity')   // 'activity' 举报活动 | 'organizer' 举报组织者
const reportOpen = ref(false)   // 详情页举报表单是否展开
const complaintBusy = ref(false)
const appealForm = ref({ reason: '' })
const appealBusy = ref(false)
const myAppeals = ref([]), myComplaints = ref([])
const recoveryForm = ref({ account: '', request_type: 1, reason: '', contact: '' })
const recoveryMine = ref(loadRecoveryMine())   // 本机保存的 {id, query_token}（localStorage 'cb_recovery'）
const recoveryQueryForm = ref({
  id: recoveryMine.value ? String(recoveryMine.value.id) : '',
  query_token: recoveryMine.value ? recoveryMine.value.query_token : '',
})
const recoveryStatusData = ref(null)
const recoveryBusy = ref(false), recoveryQueryBusy = ref(false)
const resetForm = ref({ credential: '', new_password: '' }), resetBusy = ref(false)
const adminData = ref(emptyAdminData())
const adminLoading = ref(false), adminBusyKey = ref('')
const adminResetCred = ref(null)            // {reqId, account, credential, expires_at}：仅显示一次
const adminUserQuery = ref('')
const adminBanTarget = ref(null), adminBanImpact = ref(null), adminBanImpactBusy = ref(false)
const adminBanForm = ref({ days: 7, reason: '', future_formal: 'REMOVE', organized: 'CANCEL' })
const adminAppointForm = ref({ user_id: '', note: '' })
// DG-ADM-01（2026-11-20）：活动治理里的出勤名单展开与组织者本人出勤核对。
const adminAttOpenId = ref(null), adminAttRows = ref([])
const adminAttLoading = ref(false), adminAttError = ref('')
let adminAttSeq = 0                    // 快速切换活动时丢弃旧请求的响应
function emptyAdminData() {
  return { overview: null, complaints: [], appeals: [], recovery: [], creditReviews: [], users: [], bans: [], activities: [], admins: [], actions: [] }
}
// 2026-11-15 规格：大厅与通知改为分页加载更多。
const API_PAGE_SIZE = 20
const hallPage = ref(0), hallHasMore = ref(false), hallMoreBusy = ref(false)
// G07：搜索覆盖当前类别全部页；含防抖阶段，不把尚未读取完整误报为零结果。
const hallMoreError = ref('')
const hallSearchBusy = computed(() => !!q.value.trim() && (hallLoading.value || hallMoreBusy.value || (hallHasMore.value && !hallMoreError.value)))
const hallSearchIncomplete = computed(() => !!q.value.trim() && (hallLoading.value || hallHasMore.value || !!hallMoreError.value))
let hallReadSeq = 0, hallSweepSeq = null
const myPage = ref(0), myHasMore = ref(false), myMoreBusy = ref(false)
const orgPage = ref(0), orgHasMore = ref(false), orgMoreBusy = ref(false)
let myReadSeq = 0, orgReadSeq = 0
const myRetryAppend = ref(false), orgRetryAppend = ref(false)
const notifPage = ref(0), notifHasMore = ref(false), notifMoreBusy = ref(false)
// 通知页筛选（纯前端，只作用于已加载页；未读按组最新一条判定）。
const notifFilter = ref('all')
const q = ref(''), category = ref(''), timeSlot = ref('')
// 任务 2（2026-11-11）：登录页底部的大厅摘要（公开接口，未登录也能看）。
const loginHall = ref([])
// 任务 9：深色模式开关（localStorage 'theme' 持久化；首次访问跟随系统偏好）。
const darkMode = ref(localStorage.getItem('theme')
  ? localStorage.getItem('theme') === 'dark'
  : (typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches))
// 任务 4：演示模式开关。普通用户默认看不到页脚恢复按钮；演示时在地址后加
// ?demo=1 一次即可开启（写入 localStorage 'demoMode'），页脚出现恢复入口与退出按钮。
const demoMode = ref(localStorage.getItem('demoMode') === '1')
// 任务 3：已展开的通知折叠组（key 含类型，见 groupedNotifs）。
const expandedGroups = ref(new Set())
// 任务 19：退出后的明显提示条（带重新报名入口），15 秒后自动消失。
const withdrawNotice = ref(null)
// 任务 7：组织者名单视图的数据与错误。
const rosterActivity = ref(null), rosterError = ref('')
const detailRosterState = ref(null), rosterState = ref(null)
const rosterTargetId = ref(null), rosterLoading = ref(false)
let rosterSeq = 0
const activityEditId = ref(null)
// 阶段二 CEM-08（2026-11-15）：详情页签到与出勤反馈状态。
const checkinCode = ref(null)          // {code, seconds_left, window_start, window_end}
const checkinFetchedAt = ref(0)        // 拉取签到码时的本地时间戳（算剩余秒数用）
const checkinFetching = ref(null)      // 去重：正在拉取的 activity id（null = 空闲）
const attendanceList = ref([])         // 组织者出勤核对行（每行补 _result / _evidence）
const evalForm = ref({ rating: 5, content: '' })
const evalBusy = ref(false)
const savingAttendanceId = ref(null)   // 正在保存的 user_id（按行禁用）
const ATT_RESULT_LABEL = { PRESENT: '到场', ABSENT_VERIFIED: '核实缺席', EXEMPT: '豁免', UNVERIFIED: '未核实' }
function attResultLabel(r) { return ATT_RESULT_LABEL[r] || r || '' }
const form = ref({ title: '', category: '', location: '', capacity: 4, deadline: '', start_time: '', end_time: '', description: '', conditions: '' })
// 任务 16（2026-11-19）：发布表单三个时间栏的就地格式报错（失焦校验，输入过程中不闪）。
const dtErrors = ref({ deadline: '', start_time: '', end_time: '' })
const publishErrors = ref({ title: '', category: '', location: '', capacity: '', description: '', conditions: '' })
const rescheduleErrors = ref({ deadline: '', start_time: '', end_time: '' })
// 2026-11-17：发布活动的封面选择（默认轮换 / 图库 / 上传），与表单数据分开存。
const coverChoice = ref('default')       // 'default' | 'gallery' | 'upload'
const coverGallery = ref('')             // '/img/cover-N.webp'
const coverUploaded = ref('')            // '/uploads/<uuid>.<ext>'
const coverUploading = ref(false)
const coverUploadError = ref('')
const selectedCover = computed(() => {
  if (coverChoice.value === 'gallery') return coverGallery.value
  if (coverChoice.value === 'upload') return coverUploaded.value
  return ''
})
// 2026-11-17：详情页组织者视角的封面编辑（独立状态，打开详情时按 cover_url 回显）。
const editCoverChoice = ref('default')
const editCoverGallery = ref('')
const editCoverUploaded = ref('')
const editCoverUploading = ref(false)
const editCoverError = ref('')
const editCoverBusy = ref(false)
const editSelectedCover = computed(() => {
  if (editCoverChoice.value === 'gallery') return editCoverGallery.value
  if (editCoverChoice.value === 'upload') return editCoverUploaded.value
  return ''
})
// 任务 11：演示快捷登录改为下拉自选，默认不选组织者号。
const quickAccount = ref('')
// 任务 5：校区筛选（地点文本派生，不加字段）。
const campus = ref('')
// 任务 8/18：每秒刷新一次的时钟，驱动报名截止倒计时与递补邀请剩余秒数。
const nowTick = ref(Date.now())
// 任务 9：留言草稿（详情页）与回复草稿（按留言 id）。
const messageDraft = ref('')
// 任务 17（2026-11-10）：本人发过的留言及组织者回复（GET /api/activities/{id}/messages）。
const myMessages = ref([])
const replyDrafts = ref({})
// 任务 21：活动自身状态表（activity_id -> status），/api/my 不含活动状态，
// 由公开的 /api/activities 补齐，用于隐藏已取消活动的「重新报名」。
const activityStatusMap = ref({})
// 任务 10：候补排名缓存（参与 id -> 名次），/api/my 无 rank 时由详情接口补齐。
const waitingRanks = ref({})
// 任务 10：改密码表单。
const pwForm = ref({ oldPw: '', newPw: '' })
const pwBusy = ref(false)
// G01：个人资料页（昵称 + 本人可选联系方式）。联系方式只在资料页读取/编辑，
// 不进入活动公开详情、名单或其他用户视图。
const profileForm = ref({ nickname: '', contact: '' })
const profileErrors = ref({ nickname: '', contact: '' })
const profileError = ref('')
const profileBusy = ref(false)
const profileLoading = ref(false), profileLoaded = ref(false)
let profileSeq = 0
// 任务 2：改时间表单（组织者视角，仅报名截止前）。
// G24：activityId 仅作前端草稿归属标记（不提交、不新增业务字段），防止把 A 的草稿改到 B 上。
const rescheduleOpen = ref(false)
const rescheduleForm = ref({ deadline: '', start_time: '', end_time: '', activityId: null })
const rescheduleBusy = ref(false)
// 任务 12：自定义日期时间选择器状态（target: 'form' 发布表单 | 'reschedule' 改时间）。
const picker = ref(null)
const pickerYear = ref(2026), pickerMonth = ref(11), pickerDay = ref(9), pickerHour = ref(18), pickerMinute = ref(0)
// 任务 18：已触发过自动刷新的过期邀请（按活动 id 去重，避免每秒重复拉取）。
const expiredRefreshed = ref(new Set())
let tickTimer = null
// 任务 1（2026-11-14）：提示条自动消失按实例 id 比对，避免旧定时器清掉同文案的新提示。
let msgSeq = 0
function showMsg(text, ms = 5000) {
  const id = ++msgSeq
  msg.value = text
  // 只有当前 msg 仍是本条文案时才清空：避免旧定时器误删期间直接赋值设置的报错。
  if (ms) setTimeout(() => { if (msgSeq === id && msg.value === text) msg.value = '' }, ms)
}
// G24（2026-11-20）：详情请求序号。切换活动后旧请求迟到返回时按序号丢弃，
// 避免把上一个活动的详情/错误提示盖到当前页面；同活动刷新同样递增序号（视为最新请求）。
let detailSeq = 0
// 任务 9（2026-11-16）：候补成功提示写明 2 分钟确认窗口（窗口本身仍为 120 秒，SRS R3）。
function waitlistMsg(rank) {
  const base = rank ? `你已进入候补队列，第 ${rank} 名` : '你已进入候补队列'
  return base + '。收到递补邀请后请在 2 分钟内确认，超时顺延给下一位'
}
// 任务 1（2026-11-19）：候补报名时给时间冲突非阻塞提醒。后端有意不拦候补
// （只在接受递补转正式时查冲突），前端只按「我」的正式报名做提醒。
// 任务 1（2026-11-19）：/my 的报名记录只有 start_time、没有 end_time，
// 缺失时按 activity_id 拉一次活动详情补 end_time；拉取失败就跳过该条，绝不阻断提醒主流程。
async function conflictingFormalTitles(a) {
  if (!a || !a.start_time || !a.end_time) return []
  const s = parseShanghai(a.start_time), e = parseShanghai(a.end_time)
  if (!(s < e)) return []
  const selfId = a.activity_id || a.id
  const titles = []
  for (const p of mine.value) {
    if (!p || p.status !== 'FORMAL') continue
    if ((p.activity_id ?? p.id) === selfId) continue
    if (!p.start_time) continue
    let endTime = p.end_time
    if (!endTime && p.activity_id != null) {
      try {
        const det = await api('/activities/' + p.activity_id)
        if (det && det.end_time) endTime = det.end_time
      } catch (_) { /* 详情拉取失败：跳过该条，不影响报名提示 */ }
    }
    if (!endTime) continue
    const ps = parseShanghai(p.start_time), pe = parseShanghai(endTime)
    if (!(ps < pe)) continue
    // 起止严格重叠才算冲突，首尾相接不算。
    if (ps < e && s < pe) titles.push(p.title || ('活动 #' + p.activity_id))
  }
  return titles
}

const headers = () => token.value ? { 'Authorization': 'Bearer ' + token.value, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' }
// 手机原生 App 用：后端不在本机时，在此填电脑地址（如 http://192.168.1.5:8080），留空则用当前页面地址（网页/PWA 默认）
const apiBase = ref(localStorage.getItem('apiBase') || '')
// 后端地址只在 Capacitor 原生 App 里才需要（页面不在服务器上，相对 /api/ 走不通，
// 须指明后端地址）；网页 / PWA 与后端同源，默认就是当前地址，不用填也不显示（2026-11-10 用户问）。
const isCapacitor = ref(typeof window !== 'undefined' && !!window.Capacitor)
function saveApiBase() { localStorage.setItem('apiBase', apiBase.value.trim()) }
// 2026-11-15 规格：统一走 /api/v1，解包 envelope；失败时抛出带 code / data 的错误。
function newIdemKey() {
  try { if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID() } catch (_) { /* 老浏览器兜底 */ }
  return 'idem-' + Date.now() + '-' + Math.random().toString(36).slice(2)
}
// G12（2026-11-20）：按操作缓存幂等键，结果不确定时重试沿用原键。
const idemKeyCache = new Map()
function idemKeyFor(scope) {
  if (!idemKeyCache.has(scope)) idemKeyCache.set(scope, newIdemKey())
  return idemKeyCache.get(scope)
}
function clearIdemKey(scope) { idemKeyCache.delete(scope) }
// 同一逻辑请求经冲突确认后换了载荷：不确定失败的重试必须连同确认阶段一起保留。
const pendingConfirmations = new Map()
async function postRetryable(path, body) {
  const scope = 'POST:' + path + ':' + JSON.stringify(body ?? null)
  const key = idemKeyFor(scope), sessionToken = token.value
  try {
    const result = await api(path, 'POST', body, { idempotencyKey: key })
    if (token.value === sessionToken) clearIdemKey(scope)
    return result
  } catch (e) {
    if (token.value === sessionToken && !isUncertainErr(e)) clearIdemKey(scope)
    throw e
  }
}
// 无 HTTP 状态（如网络错误）或 5xx 时，无法确定写入是否完成。
// G12：IDEMPOTENCY_IN_PROGRESS 表示原请求仍在执行、结果未定，同样按不确定处理：
// 调用方据此保留原幂等键重试，不得清键，提示处理中可重试。
function isUncertainErr(e) {
  if (e?.code === 'IDEMPOTENCY_IN_PROGRESS') return true
  const status = e?.status
  return !status || status >= 500
}
function apiFail(message, code, data, status) {
  const e = new Error(message || '请求失败')
  e.code = code
  e.data = data
  if (status) e.status = status
  return e
}
let serverOffsetMs = 0
// G13 单调守卫：最近一次采用的校准所对应的服务端时刻；旧回执不得把时钟回拨。
let serverCalibratedServerMs = 0
function calibratedNow() { return Date.now() + serverOffsetMs }
function unwrapEnvelope(j, r) {
  const status = r.status
  const isObj = !!j && typeof j === 'object' && !Array.isArray(j)
  const hasEnvelope = isObj && ('data' in j || 'error' in j || 'ok' in j || 'success' in j || 'code' in j)
  if (!hasEnvelope) {
    if (!r.ok) {
      const m = (isObj && (j.message || j.error || j.msg)) || ('请求失败 ' + status)
      throw apiFail(m, status, isObj ? j : null, status)
    }
    return j
  }
  const errObj = isObj && j.error && typeof j.error === 'object' ? j.error : null
  const okFlag = isObj ? (j.ok ?? j.success) : undefined
  const code = isObj ? j.code : undefined
  const codeOk = code === undefined || code === null || [0, 200, '0', '200', 'OK', 'SUCCESS', 'ok', 'success'].includes(code)
  if (!r.ok || errObj || okFlag === false || (okFlag === undefined && !codeOk)) {
    const message = (errObj && (errObj.message || errObj.msg)) || (isObj && (j.message || j.msg))
      || (typeof j.error === 'string' ? j.error : '') || ('请求失败 ' + status)
    const errCode = (errObj && (errObj.code ?? errObj.error_code)) ?? code ?? status
    const errData = errObj ? (errObj.data ?? null) : (isObj ? (j.data ?? null) : null)
    throw apiFail(message, errCode, errData, status)
  }
  let data = isObj && 'data' in j ? j.data : j
  // 分页元信息在 envelope 外层时合并进 data，避免丢失 has_more / total。
  if (isObj && j.meta && data && typeof data === 'object' && !Array.isArray(data)) {
    data = typeof j.meta === 'object' ? { ...j.meta, ...data } : data
  }
  if (isObj && j.serverTime) {
    const st = parseShanghai(j.serverTime)
    if (Number.isFinite(st)) {
      // G13 单调守卫：候选校准时刻早于已采用校准时刻超过 1000ms 容差的，
      // 一律视为旧回执（幂等重放）而忽略；正常新响应的校准效果不变。
      if (st >= serverCalibratedServerMs - 1000) {
        serverCalibratedServerMs = Math.max(serverCalibratedServerMs, st)
        serverOffsetMs = st - Date.now()
        // G13：首帧立即校时，不能等下一秒 tick 才修正已过期/剩余61分钟的错误入口。
        nowTick.value = st
      }
    }
  }
  return data
}
async function api(path, method = 'GET', body, opts = {}) {
  const root = (apiBase.value.trim().replace(/\/$/, '') || '') + '/api/v1'
  const h = headers()
  // 写操作带幂等键；同一逻辑操作重试时复用调用方传入的 key。
  if (method !== 'GET' && method !== 'HEAD') h['Idempotency-Key'] = opts.idempotencyKey || newIdemKey()
  const r = await fetch(root + path, { method, headers: h, body: body === undefined ? undefined : JSON.stringify(body) })
  const j = await r.json().catch(() => null)
  return unwrapEnvelope(j, r)
}
// 分页响应兼容：主流形状 {items,total,has_more}，也兼容仍返回数组的旧接口。
function pagedItems(res) {
  if (Array.isArray(res)) return res
  if (!res || typeof res !== 'object') return []
  return res.items || res.list || res.records || res.rows || []
}
function pagedHasMore(res, loadedCount, pageSize = API_PAGE_SIZE) {
  if (!res || Array.isArray(res) || typeof res !== 'object') return false
  if (typeof res.has_more === 'boolean') return res.has_more
  if (typeof res.hasMore === 'boolean') return res.hasMore
  if (typeof res.total === 'number') return loadedCount < res.total
  if (typeof res.total_count === 'number') return loadedCount < res.total_count
  return pagedItems(res).length >= pageSize
}
// 首页不传 page，交给后端默认值，避免 0/1 起始页假设出错；后续页按响应里的 page 递增。
function pageQuery(page) {
  const p = new URLSearchParams()
  if (page !== undefined && page !== null) p.set('page', String(page))
  // 后端识别 pageSize；page_size 和 size 为兼容参数，多余参数后端会忽略。
  p.set('page_size', String(API_PAGE_SIZE))
  p.set('size', String(API_PAGE_SIZE))
  p.set('pageSize', String(API_PAGE_SIZE))
  return p
}
function pageQuerySize(size) {
  const p = pageQuery()
  p.set('page_size', String(size))
  p.set('size', String(size))
  p.set('pageSize', String(size))
  return p
}
function pageOf(res, fallback = 1) {
  if (!res || typeof res !== 'object' || Array.isArray(res)) return fallback
  const n = [res.page, res.page_no, res.current_page, res.pageNum].find(v => typeof v === 'number')
  return typeof n === 'number' ? n : fallback
}
// 409 分流（G12）：仅业务冲突 CONFLICT 走「先让用户确认，再带 confirmConflict 重试」。
// IDEMPOTENCY_IN_PROGRESS 是结果不确定（见 isUncertainErr：保留原键、不弹确认）；
// IDEMPOTENCY_CONFLICT 与无 code 的其余 409 都是确定失败（普通报错、清键、不弹确认）。
// 重试 body 已变化，用新的幂等键，避免服务端回放上一次冲突响应。
function isConflict(e) {
  return !!e && e.code === 'CONFLICT'
}
function conflictText(e) {
  const d = e && e.data
  return (d && (d.message || d.reason || d.detail)) || (e && e.message) || '当前状态已变化'
}
const CONFLICT_CANCELLED = Symbol('conflict-cancelled')
async function postConfirmable(path, body, idempotencyKey, fallbackText, cancelText) {
  const sessionToken = token.value
  let pending = pendingConfirmations.get(idempotencyKey)
  if (!pending) {
    try {
      return await api(path, 'POST', body, { idempotencyKey })
    } catch (e) {
      if (!isConflict(e)) throw e
      if (token.value !== sessionToken) throw e
      if (!confirm(conflictText(e) + (fallbackText ? '\n' + fallbackText : '') + '\n是否继续？')) {
        if (cancelText) showMsg(cancelText, 3000)
        return CONFLICT_CANCELLED
      }
      pending = { body: { ...(body || {}), confirmConflict: true }, key: newIdemKey() }
      pendingConfirmations.set(idempotencyKey, pending)
    }
  }
  try {
    const result = await api(path, 'POST', pending.body, { idempotencyKey: pending.key })
    pendingConfirmations.delete(idempotencyKey)
    return result
  } catch (e) {
    if (!isUncertainErr(e)) pendingConfirmations.delete(idempotencyKey)
    throw e
  }
}
function statusText(s) {
  return { FORMAL: '正式成员', WAITING: '候补中', INVITED: '待确认', WITHDRAWN: '已退出', EXPIRED: '已过期', CANCELLED: '已取消' }[s] || s
}
// 阶段三 CEM-10（2026-11-15）：信用流水的出勤结果文案，未知值原样展示。
function creditResultText(r) {
  return { PRESENT: '到场', ABSENT_VERIFIED: '核实缺席', EXEMPT: '豁免', UNVERIFIED: '未核实' }[r] || r
}
// 阶段四 CEM-09（2026-11-15）：治理状态文案，未知值原样展示。
function complaintStateText(s) {
  return { PENDING: '待处理', RESOLVED: '已处理', DISMISSED: '已驳回' }[s] || s || ''
}
function appealStateText(s) {
  return { PENDING: '待复核', UPHELD: '维持原决定', OVERTURNED: '已撤销原处理', CORRECTED: '已更正' }[s] || s || ''
}
function recoveryStateText(s) {
  return { PENDING: '待审核', APPROVED: '已批准', REJECTED: '已驳回', COMPLETED: '已完成' }[s] || s || ''
}
function recoveryTypeText(t) { return Number(t) === 2 ? '封禁复核' : '密码找回' }
// 任务 5：只改展示文案，不改语义。放弃候补 = WITHDRAWN 且仍在排队记录里
// （详情 my_queued_at 有值；/api/my 的 queued_at 有值且 joined_at 为空）。
// 正式成员退出 = WITHDRAWN 且 joined_at 有值（detail 无排队时间）。
function isQueuedWithdrawDetail(d) { return !!d && d.my_status === 'WITHDRAWN' && !!d.my_queued_at }
function isQueuedWithdrawRecord(p) { return !!p && p.status === 'WITHDRAWN' && !!p.queued_at && !p.joined_at }
// 详情对象看 my_status，/api/my 记录看 status；组织者名单仍用 statusText()。
function myStatusText(obj) {
  if (!obj) return ''
  const st = obj.my_status !== undefined ? obj.my_status : obj.status
  if (['WAITING', 'INVITED'].includes(st) && queueClosed(obj)) return queueResultText(obj)
  // G14：EXPIRED 行优先显示后端下发的结果说明（如「报名已截止，未获得名额」），无 note 时仍为「已过期」。
  if (st === 'EXPIRED' && obj.result_note) return obj.result_note
  if (st !== 'WITHDRAWN') return statusText(st)
  const queued = obj.my_status !== undefined ? isQueuedWithdrawDetail(obj) : isQueuedWithdrawRecord(obj)
  return queued ? '已放弃候补' : '已退出'
}
// 任务 10：候补名次（优先 /api/my 自带的 rank 字段，其后是详情接口补的缓存）。
function rankOf(p) { return queueClosed(p) ? undefined : (p.my_rank ?? p.rank ?? waitingRanks.value[p.id]) }
// 任务 21：已取消活动不显示「重新报名」（参与状态 CANCELLED 本身不在候选中）。
function showResignup(p) {
  return ['WITHDRAWN', 'EXPIRED'].includes(p.status) && activityStatusMap.value[p.activity_id] !== 'CANCELLED'
}
// 仅展示用：把后端 ISO / 空格时间截成“YYYY-MM-DD HH:mm”，不改业务时间值
function fmt(s) {
  if (!s) return ''
  return String(s).replace('T', ' ').slice(0, 16)
}
// 任务 4：时间加星期几与时段标注，如“2026-11-09 周日 上午 10:41”。
// 入参是东八区墙钟字符串，直接按本地时间取星期，不做时区换算。
const WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
function periodWord(h) {
  if (h < 6) return '凌晨'
  if (h < 12) return '上午'
  if (h < 18) return '下午'
  return '晚上'
}
function fmtWeek(s) {
  if (!s) return ''
  const m = String(s).replace('T', ' ').match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/)
  if (!m) return fmt(s)
  const d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5])
  return `${m[1]}-${m[2]}-${m[3]} ${WEEK[d.getDay()]} ${periodWord(+m[4])} ${m[4]}:${m[5]}`
}
// 任务 8（2026-11-19）：大厅卡片补结束时间，只取 HH:mm，取不到返回空串。
function fmtHM(s) {
  if (!s) return ''
  const m = String(s).replace('T', ' ').match(/(\d{2}):(\d{2})/)
  if (!m) return ''
  return `${m[1]}:${m[2]}`
}
// 任务 8（2026-11-20）：登录前预览的紧凑时间——星期 + 时段 + HH:MM，如「周三晚上 19:09」。
// 与大厅卡片同一时间取法（fmtWeek 的星期/时段），只是省略日期，适合预览一行。
function fmtWeekdayHM(s) {
  if (!s) return ''
  const m = String(s).replace('T', ' ').match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/)
  if (!m) return fmt(s)
  const d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5])
  return `${WEEK[d.getDay()]}${periodWord(+m[4])} ${m[4]}:${m[5]}`
}
// 任务 8/18：服务端时间是东八区墙钟字符串（无时区后缀），浏览器
// new Date() 会按浏览器本地时区解析——本机 Chromium 是 UTC，会偏 8 小时
// （实测邀请剩余秒数多算 28916 秒）。统一按 +08:00 解析成绝对时间戳，
// 与浏览器时区无关。fmtWeek 只取星期（按墙钟分量算）不受影响，不动它。
function parseShanghai(s) {
  if (!s) return NaN
  const m = String(s).replace('T', ' ').match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})(?::(\d{2}))?/)
  if (!m) return NaN
  return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4] - 8, +m[5], +(m[6] || 0))
}
// 任务 7：详情持续时长（由起止时间算出，不新增字段）。
function durationText(a) {
  if (!a || !a.start_time || !a.end_time) return ''
  const t0 = new Date(String(a.start_time).replace(' ', 'T'))
  const t1 = new Date(String(a.end_time).replace(' ', 'T'))
  const mins = Math.round((t1 - t0) / 60000)
  if (!(mins > 0)) return ''
  if (mins < 60) return `持续约 ${mins} 分钟`
  const h = Math.floor(mins / 60), r = mins % 60
  return r ? `持续约 ${h} 小时 ${r} 分钟` : `持续约 ${h} 小时`
}
// 任务 8：报名截止倒计时（只显示，不改变报名判定逻辑；每秒由 nowTick 刷新）。
// 补充任务 8（2026-11-15）：已过截止时置空——大厅卡片名额行不再重复
// 标题徽标上的「报名已截止」（statusLabel 负责）；详情页该文案本就有
// deadlinePassed 守卫，不受影响。
function deadlineCountdown(a) {
  if (!a || !a.deadline) return ''
  const diff = parseShanghai(a.deadline) - nowTick.value
  if (diff <= 0) return ''
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '距截止还有不到 1 分钟'
  if (mins < 60) return `距截止还有 ${mins} 分钟`
  const h = Math.floor(mins / 60), r = mins % 60
  return r ? `距截止还有 ${h} 小时 ${r} 分钟` : `距截止还有 ${h} 小时`
}
// 任务 4（2026-11-10）：邀请通知倒计时。优先用后端通知行带的 expires_at
// （配合任务 4 后端改动，LEFT JOIN invitation 返回）；无该字段时解析通知文案
// 里的截止时间（后端 fmtFullMinute 固定格式「请在 2026-11-10 周二 上午 09:16 前确认」）；
// undefined = 非邀请通知或解析不到（不显示倒计时）；'已过期' = 已过截止。
function inviteCountdownText(n) {
  if (!n || n.type !== '邀请') return undefined
  let ts = NaN
  if (n.expires_at) ts = parseShanghai(n.expires_at)
  if (Number.isNaN(ts)) {
    const m = String(n.content || '').match(/请在\s*(\d{4}-\d{2}-\d{2})\s+\S+\s+\S+\s+(\d{2}):(\d{2})\s*前确认/)
    if (!m) return undefined
    ts = parseShanghai(m[1] + ' ' + m[2] + ':' + m[3])
  }
  const diff = ts - nowTick.value
  if (diff <= 0) return '已过期'
  const secs = Math.floor(diff / 1000)
  if (secs >= 60) return `还剩 ${Math.floor(secs / 60)} 分 ${secs % 60} 秒`
  return `还剩 ${secs} 秒`
}
// 通知倒计时 chip 分级：复刻 inviteCountdownText 的到期时间提取（只用于分级，
// 不改 inviteCountdownText 本身）。返回剩余毫秒；null = 非邀请或解析不到。
function notifCdRemainMs(n) {
  if (!n || n.type !== '邀请') return null
  let ts = NaN
  if (n.expires_at) ts = parseShanghai(n.expires_at)
  if (Number.isNaN(ts)) {
    const m = String(n.content || '').match(/请在\s*(\d{4}-\d{2}-\d{2})\s+\S+\s+\S+\s+(\d{2}):(\d{2})\s*前确认/)
    if (!m) return null
    ts = parseShanghai(m[1] + ' ' + m[2] + ':' + m[3])
  }
  return ts - nowTick.value
}
function notifCdClass(n) {
  const diff = notifCdRemainMs(n)
  if (diff === null) return 'normal'
  if (diff <= 0) return 'expired'
  return diff <= 600 * 1000 ? 'urgent' : 'normal'
}
// 任务 18：递补邀请剩余秒数。undefined = 无过期时间（不显示倒计时，
// 按钮照常可点）；null = 已过期；数字 = 剩余秒数。
function inviteSecondsLeft(exp) {
  if (!exp) return undefined
  const diff = parseShanghai(exp) - nowTick.value
  if (diff <= 0) return null
  return Math.floor(diff / 1000)
}
// 2026-11-17：详情页递补邀请倒计时文案（秒级，由 nowTick 每秒刷新）。
function inviteRemainText(exp) {
  const s = inviteSecondsLeft(exp)
  if (s === undefined || s === null) return ''
  return Math.floor(s / 60) + ' 分 ' + (s % 60) + ' 秒'
}
// 阶段二 CEM-08：签到码剩余秒数。以后端返回的 seconds_left 为初值，
// 减去本地已流逝的秒数；后端没给 seconds_left 时退回按 window_end 计算。
const checkinSecondsLeft = computed(() => {
  const c = checkinCode.value
  if (!c) return 0
  if (typeof c.seconds_left === 'number') {
    const elapsed = Math.floor((nowTick.value - checkinFetchedAt.value) / 1000)
    return Math.max(0, c.seconds_left - elapsed)
  }
  if (c.window_end) return Math.max(0, Math.floor((parseShanghai(c.window_end) - nowTick.value) / 1000))
  return 0
})
// 任务 2/6 返工（2026-11-09）：「变更」不再映射为「退出」。
// 退出通知自 2026-11-08 起 type 直接存「退出」（BuddyService.withdraw，
// 迁移 001 已把历史 11 行旧「变更」退出通知改写为「退出」）；
// 2026-11-09 核对：双库快照含 0 行「变更」，B 库现存 3 行「变更」
// 均为改时间通知（id 27/63/91），无旧退出行残留，兼容映射无保留必要。
// 完整编辑也复用「变更」类型；展示用通用「活动变更」，不再误称只有时间改变。
function notifTypeText(t) { return t === '变更' ? '活动变更' : t }
// 任务 9：深色模式切换（只用 REA v4 深色 token，见 style.css body.dark）。
function applyTheme() {
  document.body.classList.toggle('dark', darkMode.value)
  localStorage.setItem('theme', darkMode.value ? 'dark' : 'light')
}
function toggleTheme() { darkMode.value = !darkMode.value; applyTheme(); drawCapRings() }
// 任务 4：退出演示模式（恢复按钮随之隐藏，功能本身保留，?demo=1 可再开）。
function exitDemoMode() { demoMode.value = false; localStorage.removeItem('demoMode') }
// 任务 2：报名是否可点——状态是前后端唯一口径（任务 1 定方案 (a) 后，
// READY 且截止未到会在一个 sweep 周期内自动翻回 OPEN；此处只按状态 + 截止展示）。
function deadlinePassed(a, at = nowTick.value) {
  if (!a || !a.deadline) return false
  return parseShanghai(a.deadline) <= at
}
// G14：只派生动作/文案，不擅自把服务端 WAITING 快照写成 EXPIRED。
function queueClosed(a, at = nowTick.value) {
  return !!a && (['READY', 'RUNNING', 'ENDED', 'CANCELLED'].includes(a.activity_status || a.status)
    || deadlinePassed(a, at))
}
function queueResultText(a) {
  const phase = a?.activity_status || a?.status
  if (phase === 'CANCELLED') return '活动已取消，候补已失效'
  if (phase === 'ENDED') return '活动已结束，未获得名额'
  return '报名已截止，未获得名额'
}
function joinsQueue(a) { return isFull(a) || Number(a?.waiting_count ?? a?.waiting ?? 0) > 0 }
function canLeaveParticipation(p) {
  if (p.status === 'FORMAL') return !activityStarted(p)
  return ['WAITING', 'INVITED'].includes(p.status) && !queueClosed(p)
    && (p.status !== 'INVITED' || inviteSecondsLeft(p.invitation_expires_at) !== null)
}
// G15：阶段或校准后的开始时刻均可关闭正式退出；提交时使用当下时间再核一次。
function activityStarted(a, at = nowTick.value) {
  if (!a) return false
  if (['RUNNING', 'ENDED'].includes(a.activity_status || a.status)) return true
  const ts = parseShanghai(a.start_time)
  return Number.isFinite(ts) && ts <= at
}
function canSignup(a) {
  if (!a) return false
  return a.status === 'OPEN' && !deadlinePassed(a)
}
// 任务 6（2026-11-15）：不可点原因不再重复标题徽标上的状态词（徽标已说明状态），
// 统一改为操作引导；CANCELLED 分支保留（该按钮在已取消详情页本就不渲染）。
// 补充任务 9（2026-11-15）：详情页这个按钮已去掉 disabled，改 @click="go(detailFrom)" 回大厅
// （与「← 返回」同一目的地），所以四处共用的这句文案正好是操作引导，可直接点。
function signupDisabledReason(a) {
  if (!a) return '报名未开始'
  if (a.status === 'CANCELLED') return '活动已取消'
  // ENDED / RUNNING / OPEN 已过截止 / READY（报名未开始）：状态词已在标题徽标上，
  // 按钮不再重复，只给操作引导（四处合并为同一句，语义与逐分支写法一致）。
  return '看看其他活动'
}
// 任务 2：大厅卡片 / 详情标题的不可报标识文案（OPEN 无标识）。
function statusLabel(a) {
  if (!a) return ''
  if (a.status === 'CANCELLED') return '已取消'
  if (a.status === 'ENDED') return '已结束'
  if (a.status === 'RUNNING') return '进行中'
  if (deadlinePassed(a)) return '报名已截止'
  if (a.status === 'READY') return '报名未开始'
  return ''
}
// ===== 2026-11-17：详情页行动卡辅助（呈现层；判定只用现有字段，不新增接口） =====
// 剩余名额 = 容量 − 正式 − 有效预留（§6.4.1「可用名额扣除有效预留」），不低于 0。
function remainingSeats(a) {
  if (!a) return 0
  const formal = a.formal_count ?? a.formal ?? 0
  const reserved = a.reserved_count ?? a.reserved ?? 0
  return Math.max(0, (a.capacity ?? 0) - formal - reserved)
}
// 「仅剩」阈值：剩余 ≤ 3 或占用（正式 + 预留）≥ 80% 容量。
function scarceSeats(a) {
  if (!a || !a.capacity) return false
  const formal = a.formal_count ?? a.formal ?? 0
  const reserved = a.reserved_count ?? a.reserved ?? 0
  return remainingSeats(a) <= 3 || (formal + reserved) >= a.capacity * 0.8
}
// 报名截止分级：>24h 充裕 / ≤24h 临期 / ≤1h 紧急 / 已过期。
function deadlineUrgency(a) {
  if (!a || !a.deadline) return 'expired'
  const ts = parseShanghai(a.deadline)
  if (!Number.isFinite(ts)) return 'expired'
  const diff = ts - nowTick.value
  if (diff <= 0) return 'expired'
  if (diff <= 3600 * 1000) return 'urgent'
  if (diff <= 24 * 3600 * 1000) return 'soon'
  return 'ample'
}
// 充裕档文案：人话截止点 + 与卡片同口径的倒计时（任务 10：不再用「N 天」，
// 避免详情与卡片「33 小时 / 1 天」两套算法；今天/明天由人话点直接说清）。
function deadlineCountdownDetail(a) {
  if (!a || !a.deadline) return ''
  const diff = parseShanghai(a.deadline) - nowTick.value
  if (diff <= 0) return ''
  const head = '报名截止：' + deadlineHumanPoint(a)
  const cd = deadlineCountdown(a)
  return cd ? head + ' · ' + cd : head
}
// 行动卡状态行：终态三词只在标题徽标出现一次（§10 验收），行动卡只补充 进行中 / 报名未开始。
function signupStateBadge(a) {
  if (!a) return ''
  if (a.status === 'CANCELLED' || a.status === 'ENDED' || deadlinePassed(a)) return ''
  return statusLabel(a)
}
// 终态句：不写标题徽标上的状态词原词（已取消 / 已结束 / 报名已截止）。
// 注意：READY 按 SweepService 语义就是「截止已过、活动待开始」，所以 deadlinePassed 分支
// 必须先于 READY 判断；READY 且截止未到只存在于一个 sweep 周期内的瞬时窗口，
// 此时报名入口本就关闭，落到「暂时无法报名」才是实话（2026-11-17 验收发现：
// 旧写法先判 READY 会让已截止活动显示自相矛盾的「报名尚未开始」）。
function signupTerminalText(a) {
  if (!a) return ''
  if (['WAITING', 'INVITED'].includes(a.my_status) && queueClosed(a)) return queueResultText(a)
  // G14：详情默认视图同口径，EXPIRED 且有 result_note 时显示该结果说明。
  if (a.my_status === 'EXPIRED' && a.result_note) return a.result_note
  if (a.status === 'CANCELLED') return '组织者取消了本次活动'
  if (a.status === 'ENDED') return '活动已于 ' + fmtWeek(a.end_time) + ' 结束'
  if (a.status === 'RUNNING') return '活动正在进行中'
  if (deadlinePassed(a)) return '报名已于 ' + fmtWeek(a.deadline) + ' 截止'
  return '暂时无法报名'
}
// 行动卡主状态：参与状态优先，其次可报名，最后终态。
// 正式退出另由 G15 的开始时间守卫收起，不影响已报名状态和签到展示；
// 候补截止/终态的完整呈现另属 G14。
// CANCELLED 始终终态（旧实现也不显示退出按钮）。
const detailActionState = computed(() => {
  const a = detail.value
  if (!a) return 'none'
  if (a.status === 'CANCELLED') return 'terminal'
  if (['WAITING', 'INVITED'].includes(a.my_status) && queueClosed(a)) return 'terminal'
  if (a.my_status === 'INVITED') return 'invited'
  if (a.my_status === 'WAITING') return 'waiting'
  if (a.my_status === 'FORMAL') return 'formal'
  if (canSignup(a)) return 'signup'
  return 'terminal'
})
// 任务 6：时段归属（按开始时间，边界：凌晨 0–6 / 上午 6–9 / 上午 9–12 / 下午 12–18 / 晚上 18–24）。
// 任务 10（2026-11-13）：上午档拆细为「上午 6–9 点」「上午 9–12 点」，返回值与下拉选项值一致；
// 展示用的 periodWord 仍统一写「上午」，不受影响。
function slotOf(hour) {
  if (hour < 6) return '凌晨'
  if (hour < 9) return '上午 6–9 点'
  if (hour < 12) return '上午 9–12 点'
  if (hour < 18) return '下午'
  // 任务 15（2026-11-14）：晚上拆细为 18–21 点 / 21–24 点两档。
  if (hour < 21) return '晚上 18–21 点'
  return '晚上 21–24 点'
}
function startHour(a) {
  const m = String(a.start_time || '').match(/[T ](\d{2}):/)
  return m ? +m[1] : null
}
// 任务 11（2026-11-20）：「今天」档用开始日期（东八区墙钟前 10 位）比对。
function startDateStr(a) {
  const m = String(a.start_time || '').match(/^(\d{4}-\d{2}-\d{2})/)
  return m ? m[1] : ''
}
// 任务 14（2026-11-19）：周末筛选——只取 start_time 的墙钟日期（YYYY-MM-DD）
// 算星期（0=周日，6=周六），与 fmtWeek 同口径，不做时区换算；取不到返回 null。
function startWeekday(a) {
  const m = String(a.start_time || '').match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) return null
  return new Date(+m[1], +m[2] - 1, +m[3]).getDay()
}
// 任务 6（2026-11-20）：时段筛选先排除已结束活动（ENDED 或已过结束时间）。
// 只在选中时段档时生效；默认大厅列表不调用，排序与已结束项保持现状（11-15/11-16 决定不动）。
function activityEnded(a) {
  if (!a) return false
  if (a.status === 'ENDED' || a.status === 'CANCELLED') return true
  return !!a.end_time && parseShanghai(a.end_time) <= nowTick.value
}
// 任务 11（2026-11-20）：「今天就能去」徽标——开始日期是东八区今天且尚未开始。
// 日期只取前 10 位，与 deadlineIsToday / isNewToday 同口径；已结束的不显示。
function startsTodayUpcoming(a) {
  if (!a || !a.start_time) return false
  if (startDateStr(a) !== shanghaiTodayStr()) return false
  if (a.status === 'ENDED' || a.status === 'CANCELLED') return false
  const ts = parseShanghai(a.start_time)
  return Number.isFinite(ts) && ts > nowTick.value
}
function isFull(a) {
  if (!a) return false
  const formal = a.formal_count ?? a.formal ?? 0
  const reserved = a.reserved_count ?? a.reserved ?? 0
  return formal + reserved >= (a.capacity ?? 0)
}
// 任务 8（2026-11-10）：当日新发布判断。created_at 是东八区墙钟字符串，
// 前 10 位即东八区日期；今天的日期按 +08:00 算，与浏览器时区无关。
function shanghaiTodayStr() {
  const d = new Date(Date.now() + 8 * 3600 * 1000)
  return d.toISOString().slice(0, 10)
}
// 任务 12（2026-11-13）：时间框示例日期动态生成，不再写死已过期的 2026-11-09/10。
// 报名截止示例取今天 21:00，开始/结束示例取明天 10:00/12:00（东八区日期）。
const todayStr = computed(() => shanghaiTodayStr())
const tomorrowStr = computed(() => {
  const d = new Date(shanghaiTodayStr() + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() + 1)
  return d.toISOString().slice(0, 10)
})
function isNewToday(a) {
  if (!a || !a.created_at) return false
  const m = String(a.created_at).match(/^(\d{4}-\d{2}-\d{2})/)
  return !!m && m[1] === shanghaiTodayStr()
}
// 任务 8：报名截止日期就是东八区今天（只取日期前 10 位，与 isNewToday 同口径）。
function deadlineIsToday(a) {
  if (!a || !a.deadline) return false
  const m = String(a.deadline).match(/^(\d{4}-\d{2}-\d{2})/)
  return !!m && m[1] === shanghaiTodayStr()
}
// 任务 10（2026-11-20）：截止日期是东八区明天——沿用 deadlineIsToday 的日期取法。
function shanghaiTomorrowStr() {
  const d = new Date(shanghaiTodayStr() + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() + 1)
  return d.toISOString().slice(0, 10)
}
function deadlineIsTomorrow(a) {
  if (!a || !a.deadline) return false
  const m = String(a.deadline).match(/^(\d{4}-\d{2}-\d{2})/)
  return !!m && m[1] === shanghaiTomorrowStr()
}
// 任务 10（2026-11-20）：倒计时旁的人话截止点——今天/明天用相对说法，
// 更远的日期给完整绝对日期；统一带星期与时段（复用 WEEK / periodWord，
// 不引入日期库）。如「明天（周六）晚上 21:09」「2026-11-24（周二）晚上 21:09」。
function deadlineHumanPoint(a) {
  if (!a || !a.deadline) return ''
  const m = String(a.deadline).replace('T', ' ').match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/)
  if (!m) return ''
  const d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5])
  const day = deadlineIsToday(a) ? '今天' : (deadlineIsTomorrow(a) ? '明天' : `${m[1]}-${m[2]}-${m[3]}`)
  return `${day}（${WEEK[d.getDay()]}）${periodWord(+m[4])} ${m[4]}:${m[5]}`
}
// 任务 10：截止角标口径收敛——今天→今天截止、明天→明天截止、其余→即将截止。
function deadlineBadgeText(a) {
  if (deadlineIsToday(a)) return '今天截止'
  if (deadlineIsTomorrow(a)) return '明天截止'
  return '即将截止'
}
// 任务 5：大厅卡片按钮按「我的状态」变文案。任务 21：已取消活动只写「查看详情」。
// 任务 4（2026-11-17）：候补写「候补中 · 查看详情」，与正式成员区分。
// G23（2026-11-20）：INVITED 与 FORMAL 分开——INVITED 写「待确认 · 查看详情」，
// 与全站 statusText 的「待确认」口径一致；FORMAL 仍为「已报名 · 查看详情」。
function cardButtonText(a) {
  if (a.status === 'CANCELLED') return '查看详情'
  if (a.my_status === 'WAITING') return '候补中 · 查看详情'
  if (a.my_status === 'INVITED') return '待确认 · 查看详情'
  return a.my_status === 'FORMAL' ? '已报名 · 查看详情' : '查看详情'
}
// 任务 5：校区派生（地点文本含校区词即命中；三词皆无归「其他」；
// 地点含多个校区词时，筛任一命中词都列出）。
function campusOf(location) {
  const loc = location || ''
  if (loc.includes('望江')) return '望江'
  if (loc.includes('华西')) return '华西'
  if (loc.includes('江安')) return '江安'
  return '其他'
}
// 任务 5：登录页种子说明改实时数据（大厅已加载时取现况）。
// 任务 13：区分「大厅确实无活动」与「当前筛选下无活动」。
// 任务 15：数字与列表一致——列出筛选后的全部活动，不再只取前 3 个。
const emptyHint = computed(() => {
  if (q.value) return `没有找到含「${q.value}」的活动，换个关键词试试`
  if (campus.value) return `「${campus.value}」校区暂无活动，换个校区试试`
  if (timeSlot.value) return `「${timeSlot.value}」时段暂无活动，换个时段试试`
  if (category.value) return `「${category.value}」分类下暂无活动`
  return '暂无活动，快来发布第一个吧'
})
// 任务 13（2026-11-10）：搜索空结果的「去发活动」入口，标题预填搜索词。
function goPublishWithQuery() {
  form.value.title = q.value.trim()
  view.value = 'publish'
}
// 任务 14（2026-11-14）：空态通用入口——清空全部筛选，回到大厅全部列表。
function clearSearch() {
  q.value = ''
  category.value = ''
  timeSlot.value = ''
  campus.value = ''
  onlyHasSeats.value = false
  loadHall()
}
// 任务 9（2026-11-18）：搜索 0 结果时按类别浏览——清掉搜索词、设类别、重拉大厅。
function browseCategory(c) { q.value = ''; category.value = c; loadHall() }
// 任务 6 + 任务 12：大厅前端筛选。搜索在前端做（后端 /api/activities 的 q
// 只按标题 LIKE，改后端不在本轮前端任务内）：匹配标题 + 介绍 + 参与条件 +
// 地点（任务 4）；q 本身是「凌晨/上午/下午/晚上」时段词时，也按开始时间
// 归属匹配；再叠加时间段下拉、校区下拉筛选（任务 5，地点文本派生）。
// 类别仍走后端参数。
// G07（2026-11-20）：搜索时 ensureHallFullyLoaded 先逐页拉全，filteredHall 因此能
// 覆盖未加载页；匹配口径不变（标题 + 介绍 + 条件 + 地点）。
// 2026-11-20 任务 2：满员卡片只看「正式 + 有效预留」是否占满容量来判断已满员，不再让截止时间/状态改变这一判断。
function fullBySeats(a) {
  if (!a) return false
  return (a.formal_count ?? a.formal ?? 0) + (a.reserved_count ?? a.reserved ?? 0) >= (a.capacity ?? 0)
}
// 2026-11-20 任务 2：「还有名额」只保留正式未满且仍在报名的活动；满员与已结束均筛掉。
function hasOpenSeat(a) {
  if (!a) return false
  const today = shanghaiTodayStr()
  if (a.status === 'ENDED' || a.status === 'CANCELLED' || deadlinePassed(a)) return false
  if (a.end_time && String(a.end_time).slice(0, 10) < today) return false
  return !fullBySeats(a)
}
const filteredHall = computed(() => {
  // 任务 9（2026-11-10）：已取消活动默认不在大厅列出。
  let list = hall.value.filter(a => a.status !== 'CANCELLED')
  const needle = q.value.trim().toLowerCase()
  if (needle) {
    const periodWords = ['凌晨', '上午', '下午', '晚上']
    list = list.filter(a => {
      const hay = `${a.title || ''} ${a.description || ''} ${a.conditions || ''} ${a.location || ''}`.toLowerCase()
      if (hay.includes(needle)) return true
      if (periodWords.includes(needle)) {
        const h = startHour(a)
        if (h === null) return false
        // 任务 10：「上午」仍覆盖 6–12 点两档，不只匹配其中一档。
        if (needle === '上午') return h >= 6 && h < 12
        // 任务 15：「晚上」仍覆盖 18–24 点两档，不只匹配其中一档。
        if (needle === '晚上') return h >= 18
        return slotOf(h) === needle
      }
      return false
    })
  }
  if (campus.value) {
    list = list.filter(a => campus.value === '其他'
      ? campusOf(a.location) === '其他'
      : (a.location || '').includes(campus.value))
  }
  if (timeSlot.value) {
    list = list.filter(a => {
      // 任务 6（2026-11-20）：任一时段档都排除已结束活动；默认列表不走这里，排序不动。
      if (activityEnded(a)) return false
      // 任务 11（2026-11-20）：「今天」档只留今天开始的活动。
      if (timeSlot.value === '今天') return startDateStr(a) === shanghaiTodayStr()
      // 任务 14（2026-11-19）：「周末」档按开始日期是周六/周日匹配；其余仍按开始小时归属。
      if (timeSlot.value === '周末') {
        const w = startWeekday(a)
        return w === 0 || w === 6
      }
      const h = startHour(a)
      return h !== null && slotOf(h) === timeSlot.value
    })
  }
  if (onlyHasSeats.value) list = list.filter(hasOpenSeat)
  return list
})
// 任务 10：有搜索词且当前 0 结果（不含加载中/加载失败/补拉中）时，隐藏大厅横幅与空态封面。
const searchNoResult = computed(() => !!q.value.trim() && !hallSearchIncomplete.value && !loadError.value && !filteredHall.value.length)
// 任务 11：搜索 0 结果时，从可报名活动（OPEN、未取消、未过截止）里挑最接近的一个；
// 全部分数 ≤1 时返回 null，不强行推荐、不编造。
const searchSuggestion = computed(() => {
  // G07（2026-11-20）：补拉中结果还可能变化，先不给出推荐。
  if (hallSearchIncomplete.value) return null
  const needle = q.value.trim().toLowerCase()
  if (!needle || filteredHall.value.length) return null
  const engSyn = ['英语', '口语', '外语', '语言', 'english'].some(w => needle.includes(w))
  const photoSyn = ['拍照', '摄影', '约拍', '相机'].some(w => needle.includes(w))
  let best = null, bestScore = 0
  for (const a of hall.value) {
    if (a.status !== 'OPEN' || deadlinePassed(a)) continue
    const title = String(a.title || '').toLowerCase()
    const desc = String(a.description || '').toLowerCase()
    const cond = String(a.conditions || '').toLowerCase()
    const loc = String(a.location || '').toLowerCase()
    const text = `${title} ${desc} ${cond} ${loc}`
    let score = 0
    if (title.includes(needle)) score += 6
    if (desc.includes(needle)) score += 3
    if (cond.includes(needle)) score += 2
    if (loc.includes(needle)) score += 2
    for (const ch of needle) if (ch.trim() && text.includes(ch)) score += 0.5
    if (engSyn && a.category === '学习组') score += 4
    // 「球拍」里的「拍」不是拍照：先去掉「球拍」再判拍照相关，避免搜「拍照」推荐羽毛球活动。
    if (photoSyn && /拍(?!球)|相机|照片/.test(text.replaceAll('球拍', ''))) score += 4
    if (score > bestScore) { bestScore = score; best = a }
  }
  // 阈值 >1：单字偶然命中（如「拍照」的「拍」撞上「球拍」得 0.5 分）不推荐；
  // 同义词/子串命中（≥2 分）才推荐。无任何接近活动时返回 null，不编造。
  return bestScore > 1 ? best : null
})
// G08：活动已 ENDED 但参与记录仍是 FORMAL 的条目，从「已报名」归入「历史」。
function isEndedFormal(p) {
  return p.status === 'FORMAL' && (activityStatusMap.value[p.activity_id] === 'ENDED' || p.activity_status === 'ENDED')
}
// 任务 15：「我的活动」四个视图（SRS §3.3.7 / SDD CEM-06 的文档要求视图）。
const myFiltered = computed(() => {
  if (myTab.value === 'signed') return mine.value.filter(p => p.status === 'FORMAL' && !isEndedFormal(p))
  if (myTab.value === 'waiting') return mine.value.filter(p => ['WAITING', 'INVITED'].includes(p.status) && !queueClosed(p))
  // G05：已截止（校准时钟过 deadline，queueClosed 含 deadlinePassed 与阶段收尾）的 WAITING/INVITED 归历史，与服务端 my() 的 HISTORY 口径一致；历史卡上由 myStatusText 给结果文案。
  if (myTab.value === 'history') return mine.value.filter(p => ['WITHDRAWN', 'EXPIRED', 'CANCELLED'].includes(p.status) || isEndedFormal(p) || (['WAITING', 'INVITED'].includes(p.status) && queueClosed(p)))
  return mine.value
})
// G09：「候补」页签按状态分区渲染：INVITED（待确认）在前，WAITING（排队中）在后。
// G05：已截止/已收尾的 WAITING/INVITED 不再留在候补组，改归「历史」（见 myFiltered）。
const myWaitingGroups = computed(() => [
  { key: 'invited', title: '待确认', items: mine.value.filter(p => p.status === 'INVITED' && !queueClosed(p)) },
  { key: 'waiting', title: '排队中', items: mine.value.filter(p => p.status === 'WAITING' && !queueClosed(p)) }
])
const myEmptyText = computed(() => {
  // 任务 2（2026-11-13）：已报名页签为空但名下有候补/递补邀请时，引导去「候补」页签；
  // 完全没有报名或候补记录时仍用原句。
  const hasWaiting = mine.value.some(p => ['WAITING', 'INVITED'].includes(p.status))
  return {
    signed: hasWaiting
      ? '暂无已报名的活动。你的候补报名在「候补」页签。'
      : '暂无已报名的活动。',
    waiting: '暂无候补中的活动。', history: '暂无历史记录。'
  }[myTab.value] || '暂无参与记录。'
})
// 任务 16：通知折叠（前端展示层做，后端不改，见 changes.md 后端分工）。
// 折叠规则：同一活动 + 同一操作人、类型属于报名/候补/变更/退出，
// 与组内最新一条间隔 ≤ 30 分钟的连续通知，只展示最新一条并注明折叠条数。
// 操作人从内容提取：组织者通知以「昵称」开头，本人通知以「你」开头记为「我」。
// 邀请类通知不折叠（每条邀请有独立的确认截止时间）。
function notifActor(n) {
  const m = String(n.content || '').match(/^「([^」]+)」/)
  return m ? m[1] : '我'
}
const FOLDABLE_TYPES = ['报名', '候补', '变更', '退出']
// 任务 7（2026-11-19）：放弃候补与正式退出在库里的 type 值相同，都是 '退出'。
// 后端核对结论（runs/2026-11-19/changes-backend.md）：双库 schema 的 type CHECK
// 白名单里没有 '放弃候补'，本轮禁令下不加新 type（须同时改双库结构）；也不复用
// '候补'——会让放弃候补混进候补组被误折叠，并误触发「查看当前排名」按钮。
// 因此本函数只做纯前端显示映射，不改库、不改分组键：放弃候补正文是固定模板
// 「你已放弃活动「X」的候补。」/组织者侧「「昵称」已放弃活动「X」的候补，……」，
// 真退出正文是「已退出活动……」，两者永不重叠，故以「已放弃」判定即可。
// 同一用户对同一活动只有一条参与记录，分组键用 n.type 不会把两种语义折到一起，
// 无需改动；组织者侧通知同样走本映射（组织者侧文案同样含「已放弃」）。
function notifGroupType(n) {
  if (n.type === '退出' && String(n.content || '').includes('已放弃')) return '放弃候补'
  return n.type
}
// 2026-11-19 靶子 A：只有自侧候补通知正文含排名（后端固定模板「已进入候补队列，第 N 名」）；
// 组织者侧同 type 通知无排名，不命中。只做前端正文判定，不改分组键、不改后端。
function notifHasRank(n) {
  return n && n.type === '候补' && String(n.content || '').includes('已进入候补队列，第')
}
// 任务 3 返工（2026-11-08）：折叠只在同类型之间发生。旧实现分组 key 只有
// 活动 + 操作人、且只校验两边类型都在可折叠集合里，报名与退出会被折成一行；
// 新 key 含类型，且入组条件要求 n.type === g.latest.type。邀请类不参与折叠。
// 后端已把退出通知 type 统一存「退出」（任务 3 后端部分，历史 11 行已迁移）；
// '变更' 在可折叠集合里：改时间通知同活动 30 分钟内可折叠，与退出不再混淆
//（2026-11-09 返工核对：双库快照 0 行「变更」，B 库现存 3 行均为改时间通知）。
function notifIsNewer(a, b) {
  const ta = new Date(a.created_at), tb = new Date(b.created_at)
  return ta > tb || (ta.getTime() === tb.getTime() && (a.id ?? 0) > (b.id ?? 0))
}
const groupedNotifs = computed(() => {
  const groups = []
  for (const n of notifs.value) {
    const key = (n.activity_id ?? '') + '|' + notifActor(n) + '|' + n.type
    const g = groups.find(g => g.key === key
      && FOLDABLE_TYPES.includes(n.type) && n.type === g.latest.type
      && Math.abs(new Date(n.created_at) - new Date(g.latest.created_at)) <= 30 * 60 * 1000)
    if (g) { g.items.push(n); g.count++; if (notifIsNewer(n, g.latest)) g.latest = n } else { groups.push({ key, latest: n, items: [n], count: 1 }) }
  }
  return groups
})
function groupHasUnread(g) {
  return g.items.some(n => !n.read_at)
}
// 通知筛选派生：组内任一未读即纳入未读筛选（未读条数口径见页签，直接用 unread 徽标值）。
const visibleGroups = computed(() => notifFilter.value === 'unread'
  ? groupedNotifs.value.filter(g => groupHasUnread(g))
  : groupedNotifs.value)
// 任务 3：折叠行可展开 / 收起（点一下展开被折叠的各条，标题逐条可见）。
function toggleGroup(key) {
  const s = new Set(expandedGroups.value)
  if (s.has(key)) s.delete(key); else s.add(key)
  expandedGroups.value = s
}
// 任务 7：名单视图分组（正式 / 待确认 / 候补；待确认单列）。
// 2026-11-15 规格：roster 改为分页对象（{items,...}），兼容旧数组返回。
function rosterItems(obj) {
  const r = obj && obj.roster
  if (!r) return []
  return Array.isArray(r) ? r : (r.items || r.list || [])
}
const rosterSectionKeys = { FORMAL: ['confirmed', 'Confirmed'], INVITED: ['pending', 'Pending'], WAITING: ['waiting', 'Waiting'] }
function seedRoster(slot, d) {
  if (!d.roster && !d.roster_sections) { slot.value = null; return }
  const id = d.activity_id || d.id, items = rosterItems(d)
  const previous = String(slot.value?.activityId) === String(id) ? slot.value : null
  if (Object.values(rosterSectionKeys).every(([key]) => d.roster_sections?.[key])) {
    // 优先消费现行三类服务端分页；不预取全名单，也不把混合首批误当分类全集。
    const sections = Object.fromEntries(Object.entries(rosterSectionKeys).map(([type, [key]]) => {
      const part = d.roster_sections[key]
      return [type, { items: pagedItems(part), page: pageOf(part), pageSize: part.pageSize || 10,
        total: part.total, busy: false, error: '', failedPage: null }]
    }))
    slot.value = { mode: 'sections', activityId: id, sections, tab: previous?.tab || 'FORMAL', complete: true }
    return
  }
  // 旧响应兼容：先按原有混合分页读全，再在前端独立分三类分页。
  slot.value = { mode: 'mixed', activityId: id, items, page: pageOf(d.roster, 1),
    complete: !pagedHasMore(d.roster, items.length), busy: false, error: '',
    tab: previous?.tab || 'FORMAL', pages: { ...(previous?.pages || { FORMAL: 1, INVITED: 1, WAITING: 1 }) } }
  void loadRosterRemainder(slot)
}
async function loadRosterSection(slot, type, page) {
  const state = slot.value, section = state?.sections?.[type]
  if (state?.mode !== 'sections' || !section || section.busy || !Number.isInteger(page) || page < 1) return
  const c = membershipContext(state.activityId)
  const current = () => slot.value === state && currentMembershipContext(c)
  const param = 'roster' + rosterSectionKeys[type][1]
  section.busy = true; section.error = ''; section.failedPage = page
  try {
    for (let attempt = 0; attempt < 2; attempt++) {
      const q = new URLSearchParams({ [param + 'Page']: page, [param + 'PageSize']: section.pageSize })
      const fresh = await api('/activities/' + state.activityId + '?' + q)
      if (!current()) return
      if (!fresh.roster && !fresh.roster_sections) {
        slot.value = null
        if (slot === detailRosterState) detail.value = fresh
        else { rosterActivity.value = null; rosterError.value = '当前无权查看名单，请返回活动详情。' }
        return
      }
      const part = fresh.roster_sections?.[rosterSectionKeys[type][0]]
      if (!part || pageOf(part) !== page || !Number.isInteger(part.total)) throw new Error('分类名单分页未返回，请刷新名单')
      const lastPage = Math.max(1, Math.ceil(part.total / (part.pageSize || section.pageSize)))
      if (page > lastPage && attempt === 0) { page = lastPage; continue }
      section.items = pagedItems(part); section.page = page; section.total = part.total
      section.pageSize = part.pageSize || section.pageSize; section.failedPage = null
      return
    }
  } catch (e) { if (current()) section.error = friendlyErr(e) }
  finally { if (current()) section.busy = false }
}
function changeRosterPage(slot, type, page) {
  if (slot.value?.mode === 'sections') return loadRosterSection(slot, type, page)
  if (slot.value) slot.value.pages[type] = page
}
function retryRoster(slot) {
  const state = slot.value
  if (state?.mode === 'sections') {
    const section = state.sections[state.tab]
    return loadRosterSection(slot, state.tab, section.failedPage || section.page)
  }
  return loadRosterRemainder(slot)
}
async function loadRosterRemainder(slot) {
  const state = slot.value
  if (!state || state.busy || state.complete) return
  const c = membershipContext(state.activityId)
  const current = () => slot.value === state && currentMembershipContext(c)
  state.busy = true; state.error = ''
  try {
    while (!state.complete && current()) {
      const page = state.page + 1
      const fresh = await api('/activities/' + state.activityId + '?rosterPage=' + page + '&rosterPageSize=' + API_PAGE_SIZE)
      if (!current()) return
      if (!fresh.roster) {
        slot.value = null
        if (slot === detailRosterState) detail.value = fresh
        else { rosterActivity.value = null; rosterError.value = '当前无权查看名单，请返回活动详情。' }
        return
      }
      const items = rosterItems(fresh), merged = mergePage(state.items, items)
      const more = pagedHasMore(fresh.roster, merged.length)
      if (pageOf(fresh.roster, page) !== page || (more && merged.length === state.items.length)) throw new Error('名单分页未推进，请重新读取')
      state.items = merged; state.page = page; state.complete = !more
      if (slot === detailRosterState && detail.value) detail.value.pending_invitations = fresh.pending_invitations || []
      if (slot === rosterState && rosterActivity.value) rosterActivity.value.pending_invitations = fresh.pending_invitations || []
    }
  } catch (e) { if (current()) state.error = friendlyErr(e) }
  finally { if (slot.value === state) state.busy = false }
}
function changeDetailRosterPage(type, page) { return changeRosterPage(detailRosterState, type, page) }
function changeStandaloneRosterPage(type, page) { return changeRosterPage(rosterState, type, page) }
function loadDetailRoster() { return retryRoster(detailRosterState) }
function loadStandaloneRoster() { return retryRoster(rosterState) }
async function refreshDetailRoster() {
  const id = detail.value?.activity_id || detail.value?.id
  await refreshCurrentDetail(id)
}
function refreshStandaloneRoster() { return openRoster(rosterTargetId.value) }
// 任务 16 返工（2026-11-07）：入组时按 created_at（再按 id）取最大者更新
// g.latest（见上文新版 groupedNotifs；旧实现已由任务 3 返工替换，
// 30 分钟窗口以组内最新一条（g.latest）为锚点，逻辑不变）。
// 任务 13：fetch 失败等英文错误转中文提示。
function friendlyErr(e) {
  const m = String((e && e.message) || e || '')
  if (/Failed to fetch|NetworkError|Load failed/i.test(m)) return '网络好像断了，请检查网络后重试'
  return m
}
// 任务 12：日期时间文本框解析。接受「2026-11-09 21:00」与
// 「2026-11-09T21:00」（移动端测试填 T 格式）两种写法，统一显示为空格格式
// （年-月-日 24 小时制，与下方「已选」行一致）；非法返回 null。
// 任务 1（2026-11-10）：同时接受后端 ISO 格式（如 2026-11-12T12:00:00.000+08:00，
// 带秒/毫秒/时区后缀），否则改时间预填全部落空。
// 后端 LocalDateTime.parse 只认 T 格式，提交时用 toApiDT 转回。
function parseDTInput(s) {
  if (!s) return ''
  const m = String(s).trim().match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$/)
  if (!m) return null
  const d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5])
  if (d.getFullYear() !== +m[1] || d.getMonth() !== +m[2] - 1 || d.getDate() !== +m[3]
    || d.getHours() !== +m[4] || d.getMinutes() !== +m[5]) return null
  const p = n => String(n).padStart(2, '0')
  return `${m[1]}-${p(+m[2])}-${p(+m[3])} ${p(+m[4])}:${p(+m[5])}`
}
function toApiDT(s) {
  const n = parseDTInput(s)
  return n ? n.replace(' ', 'T') : null
}
// 任务 12：失焦时把输入归一化为「年-月-日 时:分」显示格式；非法的不动，
// 提交时再报格式错误（不打断用户输入）。
function normalizeDT(target, key) {
  const obj = target === 'form' ? form.value : rescheduleForm.value
  if (!obj[key]) return
  const n = parseDTInput(obj[key])
  if (n) obj[key] = n
}
// 任务 16（2026-11-19）：发布表单时间栏失焦时就地校验格式。空值不即时报错
//（提交时仍由 publish() 报「不能为空」）；非法清空/填写 dtErrors，合法时清空。
function validateDT(key) {
  const raw = String(form.value[key] ?? '')
  if (!raw.trim()) { dtErrors.value[key] = ''; return }
  if (parseDTInput(raw) === null) {
    dtErrors.value[key] = '格式不对，请按「年-月-日 时:分」填写，例如 ' + todayStr.value + ' 21:00'
  } else {
    dtErrors.value[key] = ''
  }
}
function onDTBlur(key) {
  normalizeDT('form', key)
  validateDT(key)
}
function onDTInput(key) {
  // v-model 的赋值与这里的事件监听在同一次事件中执行，延后一拍复检，确保读到最新值；
  // 仅在已有报错时复检（输入过程中不闪报错，改对了自动消）。
  if (dtErrors.value[key]) nextTick(() => validateDT(key))
}
// 任务 22：标题含星期词但开始时间星期不符时的非阻塞提示（发布时再 confirm 一次）。
const WEEKDAY_WORDS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六',
  '星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六']
function weekdayOfTitle(title) {
  for (let i = 0; i < WEEKDAY_WORDS.length; i++) {
    if ((title || '').includes(WEEKDAY_WORDS[i])) return i % 7
  }
  return null
}
const titleWeekdayHint = computed(() => {
  const w = weekdayOfTitle(form.value.title)
  if (w === null) return ''
  const n = parseDTInput(form.value.start_time)
  if (!n) return ''
  const d = new Date(n.replace(' ', 'T'))
  if (d.getDay() === w) return ''
  return `标题写${WEEK[w]}，但开始时间是${WEEK[d.getDay()]}，确认无误吗？`
})
// 任务 12：自定义日期时间选择器（中文习惯，年-月-日 24 小时制）。
// 不用浏览器原生 datetime-local：其显示格式跟浏览器 locale 走，
// en-US 环境下是 mm/dd/yyyy + 12 小时制，与中文「已选」行永远对不上。
const pickerTitle = computed(() => {
  if (!picker.value) return ''
  return { deadline: '选择报名截止', start_time: '选择开始时间', end_time: '选择结束时间' }[picker.value.key] || '选择日期时间'
})
const pickerDays = computed(() => new Date(pickerYear.value, pickerMonth.value, 0).getDate())
const pickerBlanks = computed(() => new Date(pickerYear.value, pickerMonth.value - 1, 1).getDay())
const pickerDisplay = computed(() => {
  const p = n => String(n).padStart(2, '0')
  return `${pickerYear.value}-${p(pickerMonth.value)}-${p(pickerDay.value)} ${WEEK[new Date(pickerYear.value, pickerMonth.value - 1, pickerDay.value).getDay()]} ${periodWord(pickerHour.value)} ${p(pickerHour.value)}:${p(pickerMinute.value)}`
})
function openPicker(target, key) {
  const obj = target === 'form' ? form.value : rescheduleForm.value
  const cur = parseDTInput(obj[key])
  const base = cur ? new Date(cur.replace(' ', 'T')) : new Date()
  // 任务 9（2026-11-13）：无现值时默认取当前时间 +1 小时（不再跳到明天 18:00）。
  if (!cur) base.setTime(base.getTime() + 60 * 60 * 1000)
  pickerYear.value = base.getFullYear(); pickerMonth.value = base.getMonth() + 1
  pickerDay.value = base.getDate(); pickerHour.value = base.getHours(); pickerMinute.value = base.getMinutes()
  picker.value = { target, key }
}
function pickerPrevMonth() {
  if (pickerMonth.value === 1) { pickerMonth.value = 12; pickerYear.value-- }
  else pickerMonth.value--
  if (pickerDay.value > pickerDays.value) pickerDay.value = pickerDays.value
}
function pickerNextMonth() {
  if (pickerMonth.value === 12) { pickerMonth.value = 1; pickerYear.value++ }
  else pickerMonth.value++
  if (pickerDay.value > pickerDays.value) pickerDay.value = pickerDays.value
}
function confirmPicker() {
  if (!picker.value) return
  const p = n => String(n).padStart(2, '0')
  const v = `${pickerYear.value}-${p(pickerMonth.value)}-${p(pickerDay.value)} ${p(pickerHour.value)}:${p(pickerMinute.value)}`
  const obj = picker.value.target === 'form' ? form.value : rescheduleForm.value
  obj[picker.value.key] = v
  // 任务 16（2026-11-19）：日历选出的值一定合法，顺手清掉该栏旧报错。
  if (picker.value.target === 'form') dtErrors.value[picker.value.key] = ''
  else if (picker.value.target === 'reschedule') rescheduleErrors.value[picker.value.key] = ''
  picker.value = null
}
// 任务 18：弱密码提示（非阻塞，仅提示；注册逻辑不改）。
const isWeakPassword = computed(() => {
  const p = password.value
  return !!p && (p.length < 8 || p.length > 64 || !/[A-Za-z]/.test(p) || !/\d/.test(p))
})
// 2026-11-17：注册页密码规则清单（与 isWeakPassword 同源拆分；仅提示，不拦截提交）。
const pwdRuleLen = computed(() => { const p = password.value; return p.length >= 8 && p.length <= 64 })
const pwdRuleLetter = computed(() => /[A-Za-z]/.test(password.value))
const pwdRuleDigit = computed(() => /\d/.test(password.value))
// ===== 2026-11-17：注册独立页（字段呈现与校验，均为前端呈现层） =====
function focusAuthField(id) {
  const el = document.getElementById(id)
  if (!el) return
  el.focus()
  if (el.scrollIntoView) el.scrollIntoView({ block: 'center' })
}
function validateRegField(name) {
  if (name === 'account') {
    const v = account.value
    if (!v) regErrors.value.account = '请输入账号'
    else if (v.length < 4) regErrors.value.account = '账号至少 4 个字符'
    else if (v.length > 32) regErrors.value.account = '账号最多 32 个字符'
    else regErrors.value.account = ''
    return !regErrors.value.account
  }
  if (name === 'nickname') {
    const v = nickname.value
    if (v && [...v].length > 30) regErrors.value.nickname = '昵称最多 30 字'
    else regErrors.value.nickname = ''
    return !regErrors.value.nickname
  }
  return true
}
function validateRegAll() {
  const aOk = validateRegField('account')
  const nOk = validateRegField('nickname')
  if (!aOk) return 'account'
  if (!nOk) return 'nickname'
  return null
}
function onRegBlur(name) { validateRegField(name) }
function onRegInput(name) {
  // v-model 的赋值与这里的事件监听在同一次事件中执行，延后一拍复检，确保读到最新值。
  if (name === 'account' && regErrors.value.account) nextTick(() => validateRegField('account'))
  if (name === 'nickname' && regErrors.value.nickname) nextTick(() => validateRegField('nickname'))
}
function onConfirmInput() {
  // 同 onRegInput：延后一拍读最新值；仅当已报错且两次已一致时清错。
  if (regConfirmError.value && passwordConfirm.value === password.value) nextTick(() => { if (passwordConfirm.value === password.value) regConfirmError.value = '' })
}
function submitRegister() {
  const first = validateRegAll()
  if (first) { focusAuthField(first === 'account' ? 'reg-account' : 'reg-nickname'); return }
  if (!passwordConfirm.value) { regConfirmError.value = '请再次输入密码'; focusAuthField('reg-password-confirm'); return }
  if (passwordConfirm.value !== password.value) { regConfirmError.value = '两次输入的密码不一致，请重新输入'; focusAuthField('reg-password-confirm'); return }
  regConfirmError.value = ''
  regPwdServerError.value = ''
  register()
}
function mapRegServerError(e) {
  const m = String((e && e.message) || '')
  if (m.includes('账号已存在')) {
    regErrors.value.account = '账号已存在，换一个试试；已有账号可点页底「去登录」'
    focusAuthField('reg-account')
    return true
  }
  if (m.includes('账号需为 4-32 字符') || m.includes('账号需为4-32')) {
    regErrors.value.account = m
    focusAuthField('reg-account')
    return true
  }
  if (m.includes('昵称需为 1-30 字') || m.includes('昵称需为1-30')) {
    regErrors.value.nickname = m
    focusAuthField('reg-nickname')
    return true
  }
  if (m.includes('密码')) {
    regPwdServerError.value = m
    focusAuthField('reg-password')
    return true
  }
  return false
}
function goAuth(target) {
  password.value = ''
  regErrors.value = { account: '', nickname: '' }
  loginErrors.value = { account: '', password: '' }
  regPwdServerError.value = ''
  loginHint.value = false
  if (authModal.value.visible) closeAuthModal()
  if (target === 'register') {
    go('register')
    // 桌面端进入注册页后聚焦账号框；移动端不自动聚焦，避免键盘弹起遮挡。
    if (window.matchMedia && window.matchMedia('(pointer:fine)').matches) {
      nextTick(() => focusAuthField('reg-account'))
    }
  } else {
    go('hall')
  }
}
// ===== 2026-11-17：登录/注册反馈居中模态（仅 auth 视图使用） =====
function isAuthViewNow() { return !user.value && view.value !== 'recovery' }
function showAuthModal(title, text, focusAfter = null) {
  if (!text) return
  authModalTrigger = (document.activeElement instanceof HTMLElement) ? document.activeElement : null
  authModal.value = { visible: true, title: title || '提示', text: String(text), focusAfter, confirmLabel: '', cancelLabel: '', onConfirm: null, onClose: null }
  document.body.style.overflow = 'hidden'
  nextTick(() => { if (authModalBtn.value) authModalBtn.value.focus() })
}
// 2026-11-17：确认框变体（双按钮；焦点默认落在「取消」上，Esc / 遮罩关闭均视为取消）。
// 2026-11-20 任务 1：showConfirmModal 增加可选 onClose——关闭（含 Esc / 遮罩 / 取消）
// 时回调，用于清除报名按钮的即时加载态；其余调用点不传，行为不变。
function showConfirmModal(title, text, { confirmLabel = '确认', cancelLabel = '取消', onConfirm = null, onClose = null, input = null, returnFocus = null } = {}) {
  if (!text) return
  authModalTrigger = returnFocus instanceof HTMLElement ? returnFocus : (document.activeElement instanceof HTMLElement ? document.activeElement : null)
  authModal.value = { visible: true, title: title || '请确认', text: String(text), focusAfter: null, confirmLabel, cancelLabel, onConfirm, onClose, input }
  document.body.style.overflow = 'hidden'
  nextTick(() => { if (authModalCancelBtn.value) authModalCancelBtn.value.focus() })
}
const authModalInputError = computed(() => {
  const input = authModal.value.input
  if (!input) return ''
  const value = String(input.value || '').trim()
  if (input.required && !value) return '请填写取消原因'
  if ([...value].length > input.maxLength) return '取消原因不能超过 ' + input.maxLength + ' 字'
  return ''
})
// 点确认先校验并关框再执行回调；关闭（含 Esc / 遮罩）不触发 onConfirm。
function confirmAuthModal() {
  if (!authModal.value.visible || authModalInputError.value) return
  const fn = authModal.value.onConfirm
  const inputValue = authModal.value.input ? authModal.value.input.value : undefined
  closeAuthModal()
  if (typeof fn === 'function') fn(inputValue)
}
function closeAuthModal() {
  if (!authModal.value.visible) return
  const f = authModal.value.focusAfter
  const onClose = authModal.value.onClose
  const trigger = authModalTrigger
  authModalTrigger = null
  authModal.value = { visible: false, title: '提示', text: '', focusAfter: null, confirmLabel: '', cancelLabel: '', onConfirm: null, onClose: null }
  if (!menuOpen.value) document.body.style.overflow = ''
  if (f) nextTick(() => focusAuthField(f))
  else if (trigger && document.contains(trigger)) nextTick(() => trigger.focus())
  if (typeof onClose === 'function') onClose()
}
// ===== 2026-11-17：移动端覆盖式侧边抽屉（仅 ≤640px；桌面顶栏行为不变） =====
function isMobileDrawer() { return typeof window !== 'undefined' && window.innerWidth <= 640 }
let drawerTouchX = null
function onDrawerTouchStart(e) { drawerTouchX = e.touches && e.touches[0] ? e.touches[0].clientX : null }
function onDrawerTouchEnd(e) {
  if (drawerTouchX == null) return
  const x = e.changedTouches && e.changedTouches[0] ? e.changedTouches[0].clientX : null
  if (x != null && x - drawerTouchX > 60) closeDrawer()
  drawerTouchX = null
}
function closeDrawer(refocus = true) {
  menuOpen.value = false
  if (refocus) nextTick(() => { if (menuBtn.value) menuBtn.value.focus() })
}
function onDrawerBreakpointChange(e) {
  if (e.matches && menuOpen.value) closeDrawer(false)
}
function onDocKeydown(e) {
  if (e.key === 'Escape') {
    if (picker.value) { picker.value = null; return }
    if (authModal.value.visible) { closeAuthModal(); return }
    if (menuOpen.value && isMobileDrawer()) { closeDrawer(); return }
  }
  // 浮层打开时把 Tab 焦点圈定在浮层面板内（确认框与信息框通用）。
  if (e.key === 'Tab' && authModal.value.visible) {
    const card = authModalCard.value
    if (!card) { e.preventDefault(); return }
    const items = Array.prototype.slice.call(card.querySelectorAll('button, a[href], input, select, textarea, [tabindex]'))
      .filter(el => !el.disabled && el.getAttribute('tabindex') !== '-1')
    if (!items.length) { e.preventDefault(); return }
    const first = items[0], last = items[items.length - 1]
    const active = document.activeElement
    if (e.shiftKey && (active === first || !card.contains(active))) { e.preventDefault(); last.focus() }
    else if (!e.shiftKey && (active === last || !card.contains(active))) { e.preventDefault(); first.focus() }
    return
  }
  if (e.key === 'Tab' && menuOpen.value && isMobileDrawer()) {
    const nav = mobileNav.value
    if (!nav) return
    const items = Array.prototype.slice.call(nav.querySelectorAll('button')).filter(el => !el.disabled)
    if (!items.length) return
    const first = items[0], last = items[items.length - 1]
    const active = document.activeElement
    if (e.shiftKey && (active === first || !nav.contains(active))) { e.preventDefault(); last.focus() }
    else if (!e.shiftKey && (active === last || !nav.contains(active))) { e.preventDefault(); first.focus() }
  }
}
async function login() {
  if (loginBusy.value) return
  // 2026-11-17：登录只判空（不泄露账号是否存在），空则聚焦对应字段、不发请求。
  loginErrors.value = { account: account.value ? '' : '请输入账号', password: password.value ? '' : '请输入密码' }
  if (loginErrors.value.account || loginErrors.value.password) {
    focusAuthField(loginErrors.value.account ? 'login-account' : 'login-password')
    return
  }
  loginBusy.value = true
  loginHint.value = false
  try {
    const j = await api('/login', 'POST', { account: account.value, password: password.value })
    token.value = j.token; localStorage.setItem('token', j.token); user.value = j.user; showMsg('登录成功')
    loginHint.value = false
    // 任务 9：登录成功后清空密码框，避免明文口令留在页面上。
    password.value = ''
    // 任务 3（换号串号）：先清掉上一个账号的缓存状态，再拉当前账号的；
    // 只拉大厅不够——顶栏未读数常驻显示，通知必须登录时就重拉，否则
    // 停在通知页换号会直接亮出上一个人的列表。
    clearAccountState()
    // 登录页是单独一页：默认进大厅（2026-11-10 游客不看内容）。
    // 2026-11-17：有来源（authReturn）时回来源；详情先刷新再展示。
    const ret = authReturn.value
    authReturn.value = null
    if (ret && ret.view === 'detail' && ret.id != null) {
      await openDetail(ret.id)
    } else if (ret && ret.view) {
      view.value = ret.view
    } else {
      view.value = 'hall'
    }
    // 任务 15（2026-11-13）：切到大厅并渲染完成后回到页顶，注册成功横幅才在视口内。
    await nextTick()
    window.scrollTo(0, 0)
    // 任务 18：登录成功横幅 5 秒后自动消失（另有 × 可随时关闭）；其他提示条不受影响。
    loadHall(); loadNotif()
    if (view.value === 'my') { loadMy(); loadOrganized(); loadCredit(); loadMyGovernance() }
  } catch (e) {
    // 2026-11-17：登录失败提示改走居中浮层（不再飘在页顶）。
    showAuthModal('登录失败', friendlyErr(e), 'login-submit')
    loginHint.value = true
  } finally { loginBusy.value = false }
}
async function quick(a) {
  // 任务 19：演示账号默认不选；未选时给出提示，不发起登录。
  if (!a) { msg.value = '请先选择一个演示账号'; return }
  account.value = a; password.value = 'Dazi@2026!'; await login()
}
// G01：个人资料完整入口。进入页面时重新读取 /me，避免资料页展示旧的联系方式。
function setProfileForm(u) {
  profileForm.value = {
    nickname: String(u?.nickname ?? ''),
    contact: String(u?.contact ?? ''),
  }
  profileErrors.value = { nickname: '', contact: '' }
  profileError.value = ''
}
function invalidateProfile() {
  profileSeq++
  profileLoading.value = false
  profileBusy.value = false
  profileLoaded.value = false
}
function currentProfileRequest(seq, ownerId, sessionToken) {
  return seq === profileSeq && view.value === 'profile' && token.value === sessionToken
    && user.value && String(user.value.id) === String(ownerId)
}
async function openProfile() {
  if (!user.value || (view.value === 'profile' && profileBusy.value)) return
  go('profile')
  setProfileForm(user.value)
  const seq = ++profileSeq, ownerId = user.value.id, sessionToken = token.value
  profileLoading.value = true
  profileLoaded.value = false
  try {
    const j = await api('/me')
    if (!currentProfileRequest(seq, ownerId, sessionToken)) return
    if (!j?.user || String(j.user.id) !== String(ownerId)) throw new Error('资料响应与当前账号不一致，请重试')
    user.value = { ...user.value, ...j.user }
    setProfileForm(user.value)
    profileLoaded.value = true
  } catch (e) {
    if (currentProfileRequest(seq, ownerId, sessionToken)) profileError.value = '资料读取失败：' + friendlyErr(e)
  } finally {
    if (currentProfileRequest(seq, ownerId, sessionToken)) profileLoading.value = false
  }
}
function validateProfile() {
  const nickname = String(profileForm.value.nickname ?? '').trim()
  const contact = String(profileForm.value.contact ?? '').trim()
  profileErrors.value = { nickname: '', contact: '' }
  if (!nickname) profileErrors.value.nickname = '昵称不能为空'
  else if ([...nickname].length > 30) profileErrors.value.nickname = '昵称最多 30 字'
  if ([...contact].length > 100) profileErrors.value.contact = '联系方式不能超过 100 字'
  return { nickname, contact, ok: !Object.values(profileErrors.value).some(Boolean) }
}
async function saveProfile() {
  // 处理器也设门禁，不能靠 disabled 阻挡程序化 submit 或读取失败后的盲写。
  if (!user.value || view.value !== 'profile' || profileBusy.value || profileLoading.value || !profileLoaded.value) return
  const checked = validateProfile()
  if (!checked.ok) return
  const seq = ++profileSeq, ownerId = user.value.id, sessionToken = token.value
  profileBusy.value = true
  profileError.value = ''
  try {
    const j = await api('/me/profile', 'PATCH', {
      nickname: checked.nickname,
      contact: checked.contact,
    })
    if (!currentProfileRequest(seq, ownerId, sessionToken)) return
    if (!j?.user || String(j.user.id) !== String(ownerId)) throw new Error('资料响应与当前账号不一致，请重新读取核对')
    user.value = { ...user.value, ...j.user }
    setProfileForm(user.value)
    showMsg('个人资料已更新')
  } catch (e) {
    if (!currentProfileRequest(seq, ownerId, sessionToken)) return
    const fields = e?.data?.fieldErrors || e?.data?.field_errors || {}
    profileErrors.value = {
      nickname: fields.nickname || '',
      contact: fields.contact || '',
    }
    profileError.value = Object.values(profileErrors.value).some(Boolean) ? '' : friendlyErr(e)
  } finally {
    // 旧账号/旧页请求的 finally 也不得释放新请求的锁。
    if (currentProfileRequest(seq, ownerId, sessionToken)) profileBusy.value = false
  }
}
async function register() {
  if (registerBusy.value) return
  registerBusy.value = true
  // 任务 3（2026-11-15）：注册失败不应留下「还没有账号？」的登录引导。
  loginHint.value = false
  try {
    // 昵称留空时取账号前 30 个 Unicode 字符（按字符计，非字节计）。
    await api('/register', 'POST', { account: account.value, password: password.value, nickname: nickname.value || [...account.value].slice(0, 30).join('') })
    await login()
    // 任务 5：login() 会把提示写成「登录成功」；注册路径须保留「注册成功」。
    // 任务 18：注册成功横幅同样 5 秒后自动消失。
    if (user.value) showMsg('注册成功，已自动登录')
  } catch (e) {
    // 2026-11-17：可映射到字段的失败同时回填字段槽位；结果型反馈统一走居中浮层。
    const text = friendlyErr(e)
    const mapped = mapRegServerError(e)
    const fieldText = regErrors.value.account || regErrors.value.nickname || regPwdServerError.value
    const focusId = mapped
      ? (regErrors.value.account ? 'reg-account' : (regErrors.value.nickname ? 'reg-nickname' : 'reg-password'))
      : null
    showAuthModal('注册失败', mapped ? (fieldText || text) : text, focusId)
  } finally { registerBusy.value = false }
}
async function resignup(aid) {
  if (signupLocked.value) return
  const returnFocus = document.activeElement
  const c = membershipContext(aid)
  let handedOff = false
  resignupBusy.value = true
  try {
    const fresh = await api('/activities/' + aid)
    if (!currentMembershipContext(c)) return
    resignupBusy.value = false
    handedOff = true
    confirmSignupConditions(fresh, submitResignup, returnFocus)
  } catch (e) { await recoverMembershipFailure(e, c) }
  finally { if (!handedOff && c.token === token.value) resignupBusy.value = false }
}
async function submitResignup(aid, body) {
  // 2026-11-20 任务 1：重新报名也加 busy 守卫，慢网下重复点只提交一次；
  // 提示条与「我的活动」按钮在 resignupBusy 期间置灰并显示「正在报名…」。
  if (resignupBusy.value) return
  resignupBusy.value = true
  const scope = 'resignup:' + aid + (body ? ':conditions-confirmed' : ''), c = membershipContext(aid)
  try {
    const j = await postConfirmable('/activities/' + aid + '/signup', body, idemKeyFor(scope), undefined, '已取消，可稍后再报')
    if (!currentMembershipContext(c)) return
    clearIdemKey(scope)
    if (j === CONFLICT_CANCELLED) return
    acknowledgedConditions.delete(String(aid))
    // 任务 19 返工：重新报名后刷新当前详情（与 signup() 一致）——
    // 否则详情仍显示已退出（名额 0/6、「报名」按钮），与横幅/接口不一致。
    // openDetail 会清空 msg，须在它之后设置提示；只刷新当前正打开的同一活动。
    await refreshCurrentDetail(aid)
    // 任务 1（2026-11-19）：冲突提醒用最新的「我的报名」；仅在详情仍是同一活动时计算。
    await loadMy()
    if (!currentMembershipContext(c)) return
    membershipNotice.value = null
    // 任务 14：重新报名也用用户语言，按重新拉到的详情实际状态写（与 signup() 一致）。
    const st = detail.value?.my_status || j?.my_status
    const rank = detail.value?.my_rank || j?.my_rank
    const conflictTitles = (detail.value && (detail.value.id === aid || detail.value.activity_id === aid))
      ? await conflictingFormalTitles(detail.value) : []
    showMsg(st === 'WAITING'
      ? waitlistMsg(rank) + (conflictTitles.length ? '。提醒：该时段你已报名「' + conflictTitles.join('」「') + '」，如递补成功需二选一' : '')
      : st === 'INVITED' ? '你收到递补邀请，请及时确认' : '你报上了，你是正式成员')
    // 任务 14：报名提示 5 秒自动消失（与登录横幅一致）；切页时 go() 也会清除。
    withdrawNotice.value = null
    loadMy()
    loadHall()
    loadNotif()
  } catch (e) {
    if (c.token === token.value && !isUncertainErr(e)) clearIdemKey(scope)
    await recoverMembershipFailure(e, c)
  } finally { if (c.token === token.value) resignupBusy.value = false }
}
// 任务 19：从退出提示条点「重新报名」。
async function resignupFromNotice() {
  if (withdrawNotice.value?.activityId) await resignup(withdrawNotice.value.activityId)
}
// 任务 3（换号串号）：按账号缓存的前端状态集中清理——通知列表、
// 未读数、我的活动（我报名的 + 我组织的）、详情页（含 my_status /
// 组织者名单，均属当前账号视角）。登录成功后、退出时、token 失效时都走这里。
function clearAccountState() { hallReadSeq++; hallSweepSeq = null; hallMoreBusy.value = false; hallLoading.value = false; hallMoreError.value = ''; cancelDrafts.clear(); rosterSeq++; rosterState.value = null; detailRosterState.value = null; rosterTargetId.value = null; rosterLoading.value = false; activityEditId.value = null; rescheduleOpen.value = false; navigationSeq++; detailSeq++; acknowledgedConditions.clear(); signupPending.value = false; signupBusy.value = false; resignupBusy.value = false; detailRefreshing.value = false; detailReadError.value = ''; membershipNotice.value = null; expiredRefreshed.value = new Set(); idemKeyCache.clear(); pendingConfirmations.clear(); actionBusy.value = new Set(); invalidateProfile(); myReadSeq++; orgReadSeq++; myPage.value = 0; orgPage.value = 0; myHasMore.value = false; orgHasMore.value = false; myMoreBusy.value = false; orgMoreBusy.value = false; activityStatusMap.value = {}; waitingRanks.value = {}; mine.value = []; organized.value = []; notifs.value = []; unread.value = 0; detail.value = null; acceptSuccess.value = null; highlightPartId.value = null; notifInviteMissing.value = null; myMessages.value = []; withdrawNotice.value = null; rosterActivity.value = null; rosterError.value = ''; credit.value = null; creditEntries.value = []; myAppeals.value = []; myComplaints.value = []; adminData.value = emptyAdminData(); adminResetCred.value = null; adminBanTarget.value = null; adminBanImpact.value = null; adminUserQuery.value = ''; userMenuOpen.value = false; notifFilter.value = 'all'; menuOpen.value = false; myError.value = ''; orgError.value = ''; profileForm.value = { nickname: '', contact: '' }; profileErrors.value = { nickname: '', contact: '' }; profileError.value = '' }
// 顶栏披露：只有 nav 的四个主工作区进入「当前页」语义；详情沿用来源分区。
const navCurrent = computed(() => ({
  hall: 'hall', my: 'my', notif: 'notif', publish: 'publish',
  detail: detailFrom.value
})[view.value] || null)
// 用户菜单：Esc 关闭并把焦点交还昵称按钮；菜单项执行完（含异步）后关闭。
function closeUserMenu(refocus) {
  userMenuOpen.value = false
  if (refocus) nextTick(() => { if (userMenuBtn.value) userMenuBtn.value.focus() })
}
// 披露组件：焦点离开整个账户区（Tab 走完菜单项）时收起，不抢焦点。
function onUserMenuFocusOut(e) {
  if (!userMenuOpen.value) return
  if (e.relatedTarget && userMenu.value && userMenu.value.contains(e.relatedTarget)) return
  closeUserMenu(false)
}
async function userMenuRun(fn) {
  try { await fn() } finally { userMenuOpen.value = false }
}
function logout() {
  token.value = ''; localStorage.removeItem('token'); user.value = null; clearAccountState(); view.value = 'hall'
  // 任务 9：退出时清空密码框。
  password.value = ''
  // 任务 2：回到登录页时刷新底部的大厅摘要。
  loadLoginHall()
}
// UI 配图（2026-11-10，用户定：用通用配图，不按分类配专用图——专用图使用场景有限）。
// 2026-11-17：活动可选封面——有 cover_url 用活动自己的，否则按 id 轮换 3 张通用封面；
// 横幅与空状态仍共用 hero。
function coverImg(activity) {
  const a = activity || {}
  if (a.cover_url) return a.cover_url
  const n = ((Number(a.id ?? a.activity_id) || 0) % 3) + 1
  return '/img/cover-' + n + '.webp'
}
// 2026-11-17：封面选择与上传。上传走 multipart，不能复用只发 JSON 的 api()，
// 但仍用同一个 envelope 解包与错误文案；Authorization 头与 headers() 口径一致。
function chooseGalleryCover() {
  coverChoice.value = 'gallery'
  if (!coverGallery.value) coverGallery.value = '/img/cover-1.webp'
}
function chooseEditGalleryCover() {
  editCoverChoice.value = 'gallery'
  if (!editCoverGallery.value) editCoverGallery.value = '/img/cover-1.webp'
}
async function uploadCover(file) {
  if (!file) throw apiFail('请选择图片', 'VALIDATION', null, 400)
  const root = (apiBase.value.trim().replace(/\/$/, '') || '') + '/api/v1'
  const fd = new FormData()
  fd.append('file', file)
  // 不手动设 Content-Type，交给浏览器带 multipart boundary。
  const h = token.value ? { 'Authorization': 'Bearer ' + token.value } : {}
  const r = await fetch(root + '/uploads/image', { method: 'POST', headers: h, body: fd })
  const j = await r.json().catch(() => null)
  const data = unwrapEnvelope(j, r)
  if (!data || !data.url) throw apiFail('上传失败，请重试', 'UPLOAD_FAILED', null, r.status)
  return data.url
}
async function onPublishCoverFile(e) {
  const file = e.target.files && e.target.files[0]
  if (!file) return
  coverUploading.value = true
  coverUploadError.value = ''
  try {
    coverUploaded.value = await uploadCover(file)
    coverChoice.value = 'upload'
    coverUploadError.value = ''
  } catch (err) {
    coverUploadError.value = friendlyErr(err)
  } finally {
    coverUploading.value = false
    // 允许再次选择同一文件时仍触发 change。
    e.target.value = ''
  }
}
async function onEditCoverFile(e) {
  const file = e.target.files && e.target.files[0]
  if (!file) return
  editCoverUploading.value = true
  editCoverError.value = ''
  try {
    editCoverUploaded.value = await uploadCover(file)
    editCoverChoice.value = 'upload'
    editCoverError.value = ''
  } catch (err) {
    editCoverError.value = friendlyErr(err)
  } finally {
    editCoverUploading.value = false
    e.target.value = ''
  }
}
// 组织者视角打开详情时按当前 cover_url 回显来源：图库第 N 张 / 上传图 / 默认轮换。
function initEditCover(d) {
  editCoverError.value = ''
  editCoverGallery.value = ''
  editCoverUploaded.value = ''
  const url = d && d.cover_url ? String(d.cover_url) : ''
  const m = url.match(/^\/img\/cover-([123])\.webp$/)
  if (m) {
    editCoverChoice.value = 'gallery'
    editCoverGallery.value = url
  } else if (url.startsWith('/uploads/')) {
    editCoverChoice.value = 'upload'
    editCoverUploaded.value = url
  } else {
    editCoverChoice.value = 'default'
  }
}
async function saveEditCover(id) {
  if (editCoverBusy.value || !detail.value) return
  editCoverBusy.value = true
  editCoverError.value = ''
  try {
    // 空串表示清除回默认（后端把 cover_url 置 NULL）。
    const j = await api('/activities/' + id + '/cover', 'PUT', { cover_url: editSelectedCover.value || '' })
    detail.value.cover_url = j && j.cover_url ? j.cover_url : null
    showMsg('封面已更新')
  } catch (e) {
    editCoverError.value = friendlyErr(e)
  } finally {
    editCoverBusy.value = false
  }
}
// Canvas 名额环：正式/容量画成圆环，中心写数字；深色模式换配色。
// 画布属性 112（CSS 56，2x 清晰度），按 data-formal / data-cap 画。
// 2026-11-17：详情页大环（144，CSS 72）带 data-remaining 时，环心改写剩余名额；
// 大厅环不带该属性，仍写「正式/容量」，两处环弧口径一致。
function drawCapRings() {
  const dark = darkMode.value
  document.querySelectorAll('canvas.cap-ring').forEach(cv => {
    const formal = Number(cv.dataset.formal), cap = Number(cv.dataset.cap)
    if (!cap || Number.isNaN(formal)) return
    const ctx = cv.getContext('2d')
    const s = cv.width
    ctx.clearRect(0, 0, s, s)
    const cx = s / 2, cy = s / 2, r = s / 2 - 9
    ctx.lineWidth = 10
    // 任务 13：深色模式空环轨道提亮到 0.45，避免空名额环看不见。
    ctx.strokeStyle = dark ? 'rgba(240,239,236,0.45)' : 'rgba(20,20,19,0.12)'
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke()
    const frac = Math.min(1, formal / cap)
    if (frac > 0) {
      ctx.strokeStyle = '#D97757'
      ctx.lineCap = 'round'
      ctx.beginPath(); ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * frac); ctx.stroke()
    }
    ctx.fillStyle = dark ? '#f0efec' : '#141413'
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    const remAttr = cv.dataset.remaining
    if (remAttr !== undefined) {
      // 详情页 144 画布：字号同比放大到 33px，环心只写剩余名额。
      ctx.font = '700 33px system-ui, sans-serif'
      ctx.fillText(String(Number(remAttr) || 0), cx, cy + 1)
    } else {
      ctx.font = (formal === 0 ? '700' : '600') + ' 26px system-ui, sans-serif'
      ctx.fillText(formal + '/' + cap, cx, cy + 1)
    }
  })
}
// 任务 4（2026-11-16）：大厅三档排序：可直接报正式名额在前、已满员（只能候补）
// 在中、已结束在后；同档内保持 API 原顺序（开始时间升序）。稳定排序，只改顺序：
// 不隐藏满员/已结束活动，也不改已取消的过滤（「我的活动-历史」不受影响）。
const hallOrder = list => [...list].sort((a, b) => hallTier(a) - hallTier(b))
function hallTier(a) {
  if (!a) return 1
  if (a.status === 'ENDED') return 2
  if (a.status === 'OPEN' && !deadlinePassed(a) && !isFull(a)) return 0
  return 1
}
function currentHallRead(seq, cat, session) {
  return seq === hallReadSeq && cat === category.value && session === token.value
}
async function loadHall() {
  const seq = ++hallReadSeq, cat = category.value, session = token.value
  hallLoading.value = true; loadError.value = ''; hallMoreError.value = ''
  hallPage.value = 0; hallHasMore.value = false; hallMoreBusy.value = false
  try {
    const params = pageQuery()
    // 保留标题/介绍/条件的本地搜索；服务端 q 仅查标题，不能先裁掉其他命中。
    if (cat) params.set('category', cat)
    const j = await api('/activities?' + params.toString())
    if (!currentHallRead(seq, cat, session)) return
    hall.value = hallOrder(pagedItems(j))
    hallPage.value = pageOf(j, 1)
    hallHasMore.value = pagedHasMore(j, hall.value.length)
  } catch (e) {
    if (!currentHallRead(seq, cat, session)) return
    loadError.value = friendlyErr(e); hall.value = []; hallHasMore.value = false
  } finally {
    if (currentHallRead(seq, cat, session)) {
      hallLoading.value = false
      await nextTick(); drawCapRings()
      if (q.value.trim()) void ensureHallFullyLoaded()
    }
  }
}
async function retryHall() { await loadHall() }
// 同一类别/会话/刷新世代追加，页码只在有效成功后推进；失败保留原页与已有结果。
async function loadMoreHall() {
  if (hallLoading.value || hallMoreBusy.value || !hallHasMore.value) return false
  const seq = hallReadSeq, cat = category.value, session = token.value
  hallMoreBusy.value = true; hallMoreError.value = ''
  try {
    const next = hallPage.value + 1, params = pageQuery(next)
    if (cat) params.set('category', cat)
    const j = await api('/activities?' + params.toString())
    if (!currentHallRead(seq, cat, session)) return false
    if (pageOf(j, next) !== next) throw new Error('分页响应未前进，请重试')
    const items = pagedItems(j)
    const seen = new Set(hall.value.map(a => String(a.id)))
    const added = items.filter(a => { const id = String(a.id); if (seen.has(id)) return false; seen.add(id); return true })
    const more = pagedHasMore(j, hall.value.length + added.length)
    if (!added.length && (items.length || more)) throw new Error('分页响应没有新增活动，请重试')
    hall.value = hallOrder(hall.value.concat(added))
    hallPage.value = next; hallHasMore.value = more
    await nextTick(); drawCapRings()
    return true
  } catch (e) {
    if (currentHallRead(seq, cat, session)) hallMoreError.value = friendlyErr(e)
    return false
  } finally { if (currentHallRead(seq, cat, session)) hallMoreBusy.value = false }
}
async function retryMoreHall() {
  if (await loadMoreHall()) void ensureHallFullyLoaded()
}
// 无固定轮数截断；用页码与新增ID检测无进展，异常时明确未搜完且可重试原页。
async function ensureHallFullyLoaded() {
  const seq = hallReadSeq
  if (hallSweepSeq === seq || hallLoading.value || hallMoreBusy.value || loadError.value || hallMoreError.value) return
  hallSweepSeq = seq
  try {
    while (seq === hallReadSeq && view.value === 'hall' && q.value.trim() && hallHasMore.value) {
      if (!await loadMoreHall()) break
    }
  } finally { if (hallSweepSeq === seq) hallSweepSeq = null }
}
let hallSearchTimer = null
watch([q, view], () => {
  if (hallSearchTimer) { clearTimeout(hallSearchTimer); hallSearchTimer = null }
  if (!q.value.trim() || view.value !== 'hall') return
  hallSearchTimer = setTimeout(() => {
    hallSearchTimer = null
    void ensureHallFullyLoaded()
  }, 300)
})
// 任务 2（2026-11-11）：登录页的大厅摘要。走公开 GET /activities（无需 token），
// 过滤规则与大厅视图一致（默认不列已取消活动），只存列表供登录页显示数量与名称。
async function loadLoginHall() {
  try {
    // 任务 2（2026-11-15）：与大厅同序——已结束排到最后，其余保持 API 原顺序。
    const p = pageQuerySize(100)
    const j = await api('/activities?' + p.toString())
    loginHall.value = hallOrder(pagedItems(j).filter(a => a.status !== 'CANCELLED'))
  } catch (_) { loginHall.value = [] }
}
async function openDetail(id) {
  navigationSeq++
  queueRefreshAt = calibratedNow()
  detailReadError.value = ''; membershipNotice.value = null
  // G24：本次请求的序号；返回后若已有更新的请求（切了活动或又刷新了详情），本条响应作废。
  const seq = ++detailSeq
  if (acceptSuccess.value && String(acceptSuccess.value.activityId) !== String(id)) acceptSuccess.value = null
  if (activityEditId.value && String(activityEditId.value) !== String(id)) activityEditId.value = null
  // G24：从 A 切到 B 时关闭改时间面板并清空草稿（同活动刷新不清，见 openReschedule 绑定 id）。
  if (rescheduleForm.value.activityId && String(rescheduleForm.value.activityId) !== String(id)) {
    rescheduleOpen.value = false
    rescheduleForm.value = { deadline: '', start_time: '', end_time: '', activityId: null }
  }
  // 阶段二 CEM-08：切换/刷新活动先清空签到码与出勤核对数据，避免串活动。
  checkinCode.value = null; checkinFetchedAt.value = 0; attendanceList.value = []
  // 阶段四 CEM-09：切换活动时清空举报/申诉草稿与对象，避免串活动。
  complaintTarget.value = 'activity'; complaintForm.value = { category: '', reason: '' }
  reportOpen.value = false
  appealForm.value = { reason: '' }
  // 任务 4（2026-11-18）：切换活动时清空上次的报名 / 留言失败提示。
  signupError.value = ''; myMessagesError.value = ''
  try {
    // 记录从哪来（大厅 / 我的活动），详情页返回时回到原地。
    if (view.value !== 'detail') detailFrom.value = view.value === 'my' ? 'my' : 'hall'
    const fresh = await api('/activities/' + id)
    // G24：迟到的旧响应直接丢弃——不覆盖 detail、不动 msg（seq 已被更新的请求顶替）。
    if (seq !== detailSeq) return
    detail.value = fresh; msg.value = ''
    // 阶段二 CEM-08：按组织者/已结束状态拉签到码或出勤核对；评价表单按 my_evaluation 预填。
    const d = detail.value
    evalForm.value = d.my_evaluation
      ? { rating: Number(d.my_evaluation.rating) || 5, content: d.my_evaluation.content || '' }
      : { rating: 5, content: '' }
    // 2026-11-17：组织者视角按当前 cover_url 回显封面编辑区。
    if (d.roster) { initEditCover(d); seedRoster(detailRosterState, d) }
    else detailRosterState.value = null
    if (d.roster && d.status === 'RUNNING') loadCheckinCode(id)
    if (d.roster && d.status === 'ENDED') loadAttendance(id)
    // 任务 17（2026-11-10）：非组织者视角拉取本人发过的留言及组织者回复；
    // 组织者走名单视图的全部留言，不拉此接口。
    if (user.value && !detail.value.roster) loadMyMessages(id); else myMessages.value = []
    // 详情是独立页（2026-11-10）：切过去并回到页顶，不再在列表里原地展开、
    // 不再跳到列表最上方——之前 scrollIntoView 就是用户说的“跳到第一个”。
    view.value = 'detail'
    await nextTick()
    window.scrollTo(0, 0)
    drawCapRings()
  } catch (e) {
    // G24：迟到的失败响应同样丢弃，避免旧活动的错误提示串到当前活动。
    if (seq !== detailSeq) return
    msg.value = '活动详情加载失败：' + friendlyErr(e)
  }
}
// OBS-5：只展示本人历史，不公开他人的事件，不把旧事件当成当前状态或顺延承诺。
function resetPartHistory() {
  partHistorySeq++
  partHistory.value = { pid: null, open: false, loading: false, error: '', loaded: false, items: [] }
}
watch([() => detail.value, view, token], resetPartHistory, { flush: 'sync' })
function togglePartHistory(e) {
  partHistory.value.open = e.target.open
  if (e.target.open && !partHistory.value.loaded && !partHistory.value.loading) void loadPartHistory()
}
async function loadPartHistory() {
  const pid = detail.value?.participation_id, aid = detail.value?.activity_id || detail.value?.id
  if (!user.value || view.value !== 'detail' || !pid || partHistory.value.loading) return
  const seq = ++partHistorySeq, c = membershipContext(aid)
  const state = partHistory.value
  state.pid = pid; state.loading = true; state.error = ''
  const current = () => seq === partHistorySeq && currentMembershipContext(c)
    && view.value === 'detail' && String(detail.value?.participation_id) === String(pid)
  try {
    const rows = await api('/participations/' + pid + '/events')
    if (!current()) return
    if (!Array.isArray(rows) || rows.some(e => !e ||
      (e.participation_id != null && String(e.participation_id) !== String(pid)) ||
      (e.activity_id != null && String(e.activity_id) !== String(aid)) ||
      (e.user_id != null && String(e.user_id) !== String(c.owner)))) throw new Error('参与记录与当前对象不一致，请重试')
    state.items = rows; state.loaded = true
  } catch (e) {
    if (current()) state.error = '参与记录读取失败：' + friendlyErr(e)
  } finally { if (current()) state.loading = false }
}
function partEventTitle(e) {
  if (e.event_type === 'SIGNUP_CLOSED') return e.from_status === 'INVITED' ? '报名截止，原邀请作废' : '报名截止，未获得名额'
  return ({ SIGNUP_FORMAL: '报名成功', SIGNUP_WAITING: '加入候补', INVITE_ISSUED: '收到递补邀请',
    INVITE_ACCEPTED: '已接受递补', INVITE_REJECTED: '已拒绝递补', INVITE_EXPIRED: '递补邀请已过期',
    WITHDRAW: '已退出活动', ABANDON: '已放弃候补', ACTIVITY_CANCELLED: '活动已取消',
    MEMBER_REMOVED: '已被移出活动', RESCHEDULED: '活动信息已变更', CONDITIONS_CONFIRMED: '已确认参与条件',
  })[e.event_type] || '参与记录更新'
}
function legacyExpiryEvent(e) { return e.event_type === 'INVITE_EXPIRED' && e.to_status === 'WAITING' }
function partEventTransition(e) {
  // 旧服务端曾记录 INVITED→WAITING；不渲染成「重回候补」，也不改写原事件数据。
  if (legacyExpiryEvent(e)) return ''
  const labels = { FORMAL: '已报名', WAITING: '候补中', INVITED: '待确认', WITHDRAWN: '已退出', EXPIRED: '已过期', CANCELLED: '已取消' }
  const after = labels[e.to_status]
  if (!after) return ''
  return labels[e.from_status] ? labels[e.from_status] + ' → ' + after : after
}
function partEventDetail(e) {
  if (legacyExpiryEvent(e) || ['SIGNUP_CLOSED', 'CONDITIONS_CONFIRMED'].includes(e.event_type)) return ''
  return e.detail || ''
}
// 任务 17（2026-11-10）：GET /activities/{id}/messages，本人只返回自己的留言。
async function loadMyMessages(id) {
  if (!token.value) { myMessages.value = []; myMessagesError.value = ''; return }
  try { myMessages.value = pagedItems(await api('/activities/' + id + '/messages')); myMessagesError.value = '' } catch (e) { myMessagesError.value = friendlyErr(e); myMessages.value = [] }
}
// 阶段二 CEM-08：组织者签到码（仅 RUNNING 且在签到窗内可用；窗口外后端 400，静默不打扰）。
async function loadCheckinCode(id) {
  if (checkinFetching.value === id) return
  checkinFetching.value = id
  try {
    const j = await api('/activities/' + id + '/checkin-code')
    if (!detail.value || (detail.value.activity_id || detail.value.id) !== id) return
    checkinFetchedAt.value = Date.now()
    checkinCode.value = { code: j.code, seconds_left: j.seconds_left, window_start: j.window_start, window_end: j.window_end }
  } catch (_) {
    if (detail.value && (detail.value.activity_id || detail.value.id) === id) checkinCode.value = null
  } finally { if (checkinFetching.value === id) checkinFetching.value = null }
}
// 阶段二 CEM-08：成员签到（输入组织者公布的签到码；429 限流文案由后端透传）。
async function doCheckin(d) {
  if (!d) return
  const id = d.activity_id || d.id
  const input = prompt('请输入组织者公布的 6 位签到码', '')
  if (input === null) return
  const code = String(input).trim()
  if (!code) return
  try {
    await api('/activities/' + id + '/checkins', 'POST', { code })
    try { await openDetail(id) } catch (_) {}
    showMsg('签到成功')
  } catch (e) { showMsg(friendlyErr(e)) }
}
// 阶段二 CEM-08：组织者出勤核对列表（每行补可编辑的 _result / _evidence）。
async function loadAttendance(id) {
  try {
    const j = await api('/activities/' + id + '/attendance')
    if (!detail.value || (detail.value.activity_id || detail.value.id) !== id) return
    attendanceList.value = pagedItems(j).map(a => ({ ...a, _result: a.result || 'UNVERIFIED', _evidence: '' }))
  } catch (e) { showMsg(friendlyErr(e)) }
}
// 阶段二 CEM-08：保存单行出勤结论（带 version 做乐观锁；409 等错误直接提示）。
async function saveAttendance(aid, a) {
  if (!a || !aid || savingAttendanceId.value === a.user_id) return
  savingAttendanceId.value = a.user_id
  try {
    await api('/activities/' + aid + '/attendance/' + a.user_id, 'PUT', {
      result: a._result, evidence: (a._evidence || '').trim(), version: a.version,
    })
    showMsg('出勤已保存')
    await loadAttendance(aid)
  } catch (e) { showMsg(friendlyErr(e)) } finally { savingAttendanceId.value = null }
}
// 阶段二 CEM-08：提交/修改本人评价（仅到场成员可评价）。
async function submitEvaluation(d) {
  if (!d || evalBusy.value) return
  const id = d.activity_id || d.id
  evalBusy.value = true
  try {
    await api('/activities/' + id + '/evaluations', 'POST', {
      rating: Number(evalForm.value.rating) || 5, content: evalForm.value.content || '',
    })
    try { await openDetail(id) } catch (_) {}
    showMsg('评价已提交')
  } catch (e) { showMsg(friendlyErr(e)) } finally { evalBusy.value = false }
}
function membershipContext(aid) {
  return { aid, token: token.value, owner: user.value?.id, navigation: navigationSeq }
}
function currentMembershipContext(c) {
  return c.token === token.value && c.owner === user.value?.id && c.navigation === navigationSeq
}
// 原地重查，不导航、不清草稿/横幅；迟到读响应不能覆盖新活动或新会话。
async function refreshCurrentDetail(id) {
  if (view.value !== 'detail' || String(detail.value?.activity_id || detail.value?.id) !== String(id)) return false
  const seq = ++detailSeq, c = membershipContext(id)
  detailRefreshing.value = true
  try {
    const fresh = await api('/activities/' + id)
    if (seq !== detailSeq || !currentMembershipContext(c)) return false
    detail.value = fresh
    if (fresh.roster) seedRoster(detailRosterState, fresh)
    else detailRosterState.value = null
    detailReadError.value = ''
    return true
  } catch (e) {
    if (seq === detailSeq && currentMembershipContext(c)) detailReadError.value = '状态读取失败：' + friendlyErr(e)
    return false
  } finally {
    if (seq === detailSeq && currentMembershipContext(c)) detailRefreshing.value = false
  }
}
async function refreshMembership(id) {
  if (view.value === 'detail') return refreshCurrentDetail(id)
  if (view.value === 'my') return loadMy()
  return false
}
async function recoverMembershipFailure(e, c, { signup: isSignup = false } = {}) {
  if (!currentMembershipContext(c)) return
  if (e.status === 401) {
    const ret = { view: 'detail', id: c.aid }
    closeAuthModal()
    token.value = ''; localStorage.removeItem('token'); user.value = null
    clearAccountState(); view.value = 'hall'; authReturn.value = ret
    showAuthModal('登录已失效', '请重新登录。登录后将返回原活动并重新查询状态，不会自动重发操作。')
    return
  }
  const queried = await refreshMembership(c.aid)
  if (!currentMembershipContext(c)) return
  const text = (isUncertainErr(e) ? '提交结果暂不确定：' : '操作未完成：') + friendlyErr(e)
    + (queried ? '；已重新查询最新状态，请以当前状态为准。' : '；状态重查失败，请先重新查询，不要反复提交。')
  membershipNotice.value = { activityId: c.aid, text }
  if (isSignup) signupError.value = text
  else msg.value = text
}
// G16：首次/重报共用一步明确同意；确认仅保留在当前会话与相同条件文本下。
function confirmSignupConditions(a, send, returnFocus = document.activeElement) {
  if (!a || signupLocked.value) return
  const id = a.activity_id || a.id, c = membershipContext(id)
  if (!canSignup(a) || deadlinePassed(a, calibratedNow())) { showMsg('当前已不可报名，请刷新活动状态'); return }
  const conditions = String(a.conditions || '').trim()
  signupError.value = ''
  signupPending.value = true
  const submit = (confirmed = false) => {
    signupPending.value = false
    if (!currentMembershipContext(c)) return
    if (deadlinePassed(a, calibratedNow())) { showMsg('报名已截止，请刷新活动状态'); return }
    if (confirmed) acknowledgedConditions.set(String(id), conditions)
    void send(id, confirmed ? { conditions_confirmed: true } : undefined)
  }
  if (!conditions) { submit(); return }
  if (acknowledgedConditions.get(String(id)) === conditions) { submit(true); return }
  const openConfirm = () => {
    if (!currentMembershipContext(c)) { signupPending.value = false; return }
    showConfirmModal('最后确认一下就能报上', '参与条件：' + conditions + '\n点继续报名即表示已阅读并同意以上条件。', {
      returnFocus, confirmLabel: '我已阅读，继续报名', onConfirm: () => submit(true),
      onClose: () => { if (c.token === token.value) signupPending.value = false },
    })
  }
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(openConfirm)
  else openConfirm()
}
function requestSignup(a) { confirmSignupConditions(a, signup) }
async function signup(id, body) {
  if (signupBusy.value) return
  signupBusy.value = true
  // 任务 4（2026-11-18）：失败提示就地呈现，每次提交先清上次的报名失败提示。
  signupError.value = ''
  const scope = 'signup:' + id + (body ? ':conditions-confirmed' : ''), c = membershipContext(id)
  try {
    // CONFLICT 确认后仍由 postConfirmable 保留原 body、带 confirmConflict 换键提交。
    const j = await postConfirmable('/activities/' + id + '/signup', body, idemKeyFor(scope), undefined, '已取消，可稍后再报')
    if (!currentMembershipContext(c)) return
    clearIdemKey(scope)
    if (j === CONFLICT_CANCELLED) return
    acknowledgedConditions.delete(String(id))
    // 任务 1 + P1-6：报名返回只含 detail() 的字段（无时间/地点/组织者），
    // 直接用它覆盖详情会让 P1-6 那行变空白；改走重新拉详情（全字段），
    // 再置提示（openDetail 会清空 msg，须在它之后设置）。
    await refreshCurrentDetail(id)
    // 任务 1（2026-11-19）：冲突提醒用最新的「我的报名」。
    await loadMy()
    if (!currentMembershipContext(c)) return
    signupError.value = ''; membershipNotice.value = null
    // 任务 14：报名成功提示改用户语言，按重新拉到的详情实际状态写。
    const st = detail.value?.my_status || j?.my_status
    const rank = detail.value?.my_rank || j?.my_rank
    const conflictTitles = await conflictingFormalTitles(detail.value)
    showMsg(st === 'WAITING'
      ? waitlistMsg(rank) + (conflictTitles.length ? '。提醒：该时段你已报名「' + conflictTitles.join('」「') + '」，如递补成功需二选一' : '')
      : st === 'INVITED' ? '你收到递补邀请，请及时确认' : '你报上了，你是正式成员')
    // 任务 14：报名提示 5 秒自动消失（与登录横幅一致）；切页时 go() 也会清除。
    // 任务 8（2026-11-14）：报名成功后清除退出提示横幅。
    withdrawNotice.value = null
    loadHall()
    loadNotif()
  } catch (e) {
    if (c.token === token.value && !isUncertainErr(e)) clearIdemKey(scope)
    await recoverMembershipFailure(e, c, { signup: true })
  } finally { if (c.token === token.value) signupBusy.value = false }
}
// 任务 4（2026-11-18）：报名失败后就地重试（直接调 signup，不重弹参与条件确认框）。
async function retrySignup() {
  if (!detail.value || signupBusy.value) return
  requestSignup(detail.value)
}
// 任务 2：报名失败文案与事实一致——后端仍可能返回「活动不在报名期」
// （如 READY 未翻回的窗口期），按截止时间翻译，不再原样抛给用户。
function friendlySignupErr(e) {
  const m = String((e && e.message) || e || '')
  if (/活动不在报名期/.test(m)) {
    if (detail.value && deadlinePassed(detail.value)) return '报名已截止'
    return '报名未开始，请稍后再试'
  }
  if (/已过报名截止时间/.test(m)) return '报名已截止'
  return friendlyErr(e)
}
// 2026-11-17：判断本次退出是正式退出还是放弃候补（详情页确认框与 withdraw 共用）。
function withdrawIsQueued(pid, aid) {
  const queuedStatus = s => ['WAITING', 'INVITED'].includes(s)
  return (detail.value && (detail.value.activity_id || detail.value.id) === aid)
    ? queuedStatus(detail.value.my_status)
    : queuedStatus(mine.value.find(p => p.id === pid)?.status)
}
// 2026-11-17：详情页退出 / 放弃候补的二次确认（§6.3、§6.4.1）。
function formalWithdrawalStarted(pid, aid) {
  if (withdrawIsQueued(pid, aid)) return false
  const a = view.value === 'detail' && detail.value && String(detail.value.activity_id || detail.value.id) === String(aid)
    ? detail.value : mine.value.find(p => String(p.id) === String(pid))
  return activityStarted(a, calibratedNow())
}
function requestWithdraw(pid, aid, title) {
  if (participationLocked(pid, aid)) return
  if (formalWithdrawalStarted(pid, aid)) { showMsg('活动已开始，无法退出'); return }
  showConfirmModal('确认操作', withdrawIsQueued(pid, aid)
    ? '确认放弃候补排队吗？放弃后将退出队列，如需再排队请重新报名。'
    : '确认退出本次活动吗？退出后名额将按顺序递补给候补的同学。', {
    onConfirm: () => withdraw(pid, aid, title),
  })
}
async function withdraw(pid, aid, title) {
  const c = membershipContext(aid)
  const record = view.value === 'detail' && String(detail.value?.activity_id || detail.value?.id) === String(aid)
    ? { ...detail.value, status: detail.value.my_status, activity_status: detail.value.status } : mine.value.find(p => String(p.id) === String(pid))
  if (record && ['WAITING', 'INVITED'].includes(record.status) && !canLeaveParticipation(record)) { showMsg('候补已失效，请刷新当前状态'); return }
  // 确认浮层可能跨过开始边界，不能仅靠页面隐藏按钮。
  if (formalWithdrawalStarted(pid, aid)) { showMsg('活动已开始，无法退出'); return }
  const unlock = lockActionKeys(['part-' + pid, 'member-' + aid])
  if (!unlock) return
  // 任务 5：调用 API 前先记下原状态（成功后状态已变，取不到是不是候补）。
  // 2026-11-15 规格：WAITING / INVITED 一律「放弃候补」，走 abandon 接口。
  // G10：详情页与「我的活动」列表都经 requestWithdraw 确认后再提交。
  try {
    const wasQueued = withdrawIsQueued(pid, aid)
    await postRetryable('/participations/' + pid + (wasQueued ? '/abandon' : '/withdraw'))
    // 任务 3-1：详情刷新会清空提示（openDetail 置空 msg），先等刷新完成再置提示；
    // 刷新失败也不吞掉「已退出」。
    if (!currentMembershipContext(c)) return
    await refreshCurrentDetail(aid)
    if (!currentMembershipContext(c)) return
    // 任务 19：退出提示更明显、停留更久（15 秒）、带重新报名入口。
    // 任务 5：提示文案区分「放弃候补」与「正式成员退出」。
    const t = title || ''
    withdrawNotice.value = {
      activityId: aid,
      title: t,
      text: wasQueued
        ? (t ? `已放弃活动「${t}」的候补排队。` : '已放弃该活动的候补排队。')
        : (t ? `已退出活动「${t}」。` : '已退出活动。'),
    }
    msg.value = ''
    const snap = withdrawNotice.value
    setTimeout(() => { if (withdrawNotice.value === snap) withdrawNotice.value = null }, 15000)
    if (view.value === 'my') { loadMy(); loadOrganized(); loadCredit(); loadMyGovernance() } else { loadHall() }
    loadNotif()
  } catch (e) { await recoverMembershipFailure(e, c) } finally { unlock() }
}
// 任务 7：组织者名单视图。复用详情接口（组织者才返回 roster 字段，
// 非组织者无 roster 字段，后端行为不变；此处只做展示层分支）。
async function openRoster(id) {
  if (id == null) return
  go('roster', { load: false })
  const seq = ++rosterSeq, c = membershipContext(id)
  if (String(rosterTargetId.value) !== String(id)) { rosterActivity.value = null; rosterState.value = null }
  rosterTargetId.value = id
  rosterError.value = ''; rosterLoading.value = true
  try {
    const d = await api('/activities/' + id)
    if (seq !== rosterSeq || !currentMembershipContext(c)) return
    if (!d.roster) { rosterActivity.value = null; rosterState.value = null; rosterError.value = '仅组织者可查看名单。'; return }
    rosterActivity.value = d
    seedRoster(rosterState, d)
  } catch (e) {
    if (seq === rosterSeq && currentMembershipContext(c)) rosterError.value = '名单读取失败：' + friendlyErr(e)
  } finally { if (seq === rosterSeq && currentMembershipContext(c)) rosterLoading.value = false }
}
// 2026-11-15 规格：组织者移出成员，先弹框填原因，再提交。
async function removeMember(r, activityId) {
  if (!r) return
  const aid = activityId || rosterActivity.value?.activity_id || rosterActivity.value?.id || detail.value?.activity_id || detail.value?.id
  if (!aid) return
  const unlock = lockActionKeys(['member-' + aid])
  if (!unlock) return
  try {
    const reason = prompt(`移出成员「${r.nickname}」的原因：`, '')
    if (reason === null) return
    const text = reason.trim()
    if (!text) { showMsg('请填写移出原因'); return }
    await postRetryable('/activities/' + aid + '/members/' + r.user_id + '/remove', { reason: text })
    showMsg('已移出该成员')
    if (view.value === 'roster') await openRoster(aid)
    else if (detail.value) { try { await openDetail(aid) } catch (_) {} }
    loadMy(); loadOrganized()
  } catch (e) { showMsg(friendlyErr(e)) } finally { unlock() }
}
async function accept(id, ctx) {
  const aid = ctx?.activityId ?? invitationActivityId(id)
  const unlock = lockActionKeys(['inv-' + id, ...(aid != null ? ['member-' + aid] : [])])
  if (!unlock) return
  const scope = 'accept:' + id, c = membershipContext(aid)
  try {
    // CONFLICT 确认后仍由 postConfirmable 带 confirmConflict 换键提交。
    const j = await postConfirmable('/invitations/' + id + '/accept', undefined, idemKeyFor(scope), '名额状态可能已变化。')
    if (!currentMembershipContext(c)) return
    clearIdemKey(scope)
    if (j === CONFLICT_CANCELLED) return
    // 2026-11-19 靶子 B：先 await openDetail 刷新（它内部会清 msg），再设成功横幅与入口，
    // 否则详情页路径上横幅会被 openDetail 的 msg.value = '' 立刻清掉、入口永不出现。
    // 候补列表路径 detail.value 为 null，不走 openDetail，行为不变。
    await refreshCurrentDetail(aid)
    if (!currentMembershipContext(c)) return
    msg.value = '已接受递补'
    msgAction.value = { text: '已接受递补', label: '查看我报名的活动', run: () => { myTab.value = 'signed'; go('my') } }
    acceptSuccess.value = ctx || (detail.value ? { activityId: detail.value.id || detail.value.activity_id, title: detail.value.title } : null)
    loadMy(); loadNotif()
  } catch (e) {
    if (c.token === token.value && !isUncertainErr(e)) clearIdemKey(scope)
    await recoverMembershipFailure(e, c)
  } finally { unlock() }
}
// 2026-11-17：详情页拒绝递补的二次确认（§6.3）；「我的活动」列表仍一键直达。
function requestReject(id) {
  if (invitationLocked(id)) return
  showConfirmModal('确认操作', '确认拒绝本次递补邀请吗？拒绝后将退出候补队列，如需再排队请重新报名。', {
    onConfirm: () => reject(id),
  })
}
async function reject(id) {
  const aid = invitationActivityId(id), c = membershipContext(aid)
  const unlock = lockActionKeys(['inv-' + id, ...(aid != null ? ['member-' + aid] : [])])
  if (!unlock) return
  try {
    await postRetryable('/invitations/' + id + '/reject')
    // 先刷新详情再设横幅：openDetail 成功会把 msg 清空，反序设置横幅会被覆盖掉。
    if (!currentMembershipContext(c)) return
    await refreshCurrentDetail(aid)
    if (!currentMembershipContext(c)) return
    msg.value = '已拒绝递补'
    acceptSuccess.value = null
    msgAction.value = null
    loadMy(); loadNotif()
  } catch (e) { await recoverMembershipFailure(e, c) } finally { unlock() }
}
// 任务 7（2026-11-20）：/my 与 /my/organized 的记录不含 end_time，
// 按活动 id 拉一次详情补齐，供卡片显示「开始 …–HH:MM」；失败逐条跳过，不挡列表。
async function fillEndTimes(list, key) {
  const pending = list.filter(x => x && !x.end_time && x[key] != null)
  await Promise.all(pending.map(async x => {
    try {
      const d = await api('/activities/' + x[key])
      if (d && d.end_time) x.end_time = d.end_time
      if (d && d.start_time && !x.start_time) x.start_time = d.start_time
    } catch (_) { /* 详情拉取失败：该条不显示结束时间，不影响其他卡片 */ }
  }))
}
// G05：每一页都补齐相同的结束时间/活动阶段/候补名次，不能只丰富第一页。
async function hydrateMyItems(items) {
  await Promise.all(items.map(async p => {
    if (!p || p.activity_id == null) return
    try {
      const d = await api('/activities/' + p.activity_id)
      if (d?.end_time) p.end_time = d.end_time
      if (d?.start_time) p.start_time = d.start_time
      if (d?.status) p.activity_status = d.status
      if (d?.deadline) p.deadline = d.deadline
      if (d?.my_status != null) {
        p.status = d.my_status
        p.invitation_id = d.invitation_id ?? null
        p.invitation_expires_at = d.invitation_expires_at ?? null
      }
      if (d?.my_rank != null) p.my_rank = d.my_rank
      else if (p.status !== 'WAITING' || queueClosed(p)) { delete p.my_rank; delete p.rank }
    } catch (_) { /* 单条补读失败保留原记录，不吞掉列表；服务端仍是最终裁定。 */ }
  }))
}
async function refreshLoadedMy() {
  const seq = myReadSeq, sessionToken = token.value
  const items = mine.value.map(p => ({ ...p }))
  await hydrateMyItems(items)
  if (seq !== myReadSeq || sessionToken !== token.value || view.value !== 'my') return
  mine.value = items
  activityStatusMap.value = { ...activityStatusMap.value, ...Object.fromEntries(
    items.filter(p => p.activity_status).map(p => [p.activity_id, p.activity_status])) }
}
function mergePage(current, items) {
  return [...new Map(current.concat(items).map(item => [String(item.id), item])).values()]
}
async function loadMy(append = false) {
  if (append && (myMoreBusy.value || !myHasMore.value)) return false
  const seq = ++myReadSeq, sessionToken = token.value
  myMoreBusy.value = true
  try {
    const p = pageQuerySize(50)
    if (append) p.set('page', String(myPage.value + 1))
    const res = await api('/my?' + p.toString())
    const items = pagedItems(res)
    await hydrateMyItems(items)
    if (seq !== myReadSeq || token.value !== sessionToken) return false
    mine.value = mergePage(append ? mine.value : [], items)
    myPage.value = pageOf(res, append ? myPage.value + 1 : 1)
    myHasMore.value = items.length > 0 && pagedHasMore(res, mine.value.length, 50)
    activityStatusMap.value = { ...activityStatusMap.value, ...Object.fromEntries(
      items.filter(p => p.activity_status).map(p => [p.activity_id, p.activity_status])) }
    myError.value = ''
    return true
  } catch (e) {
    if (seq === myReadSeq && token.value === sessionToken) { myError.value = friendlyErr(e); myRetryAppend.value = append }
    return false
  } finally {
    if (seq === myReadSeq && token.value === sessionToken) myMoreBusy.value = false
  }
}
function loadMoreMy() { return loadMy(true) }
async function loadOrganized(append = false) {
  if (append && (orgMoreBusy.value || !orgHasMore.value)) return false
  const seq = ++orgReadSeq, sessionToken = token.value
  orgMoreBusy.value = true
  try {
    const p = pageQuerySize(50)
    if (append) p.set('page', String(orgPage.value + 1))
    const res = await api('/my/organized?' + p.toString())
    const items = pagedItems(res)
    await fillEndTimes(items, 'id')
    if (seq !== orgReadSeq || token.value !== sessionToken) return false
    organized.value = mergePage(append ? organized.value : [], items)
    orgPage.value = pageOf(res, append ? orgPage.value + 1 : 1)
    orgHasMore.value = items.length > 0 && pagedHasMore(res, organized.value.length, 50)
    orgError.value = ''
    return true
  } catch (e) {
    if (seq === orgReadSeq && token.value === sessionToken) { orgError.value = friendlyErr(e); orgRetryAppend.value = append }
    return false
  } finally {
    if (seq === orgReadSeq && token.value === sessionToken) orgMoreBusy.value = false
  }
}
function loadMoreOrganized() { return loadOrganized(true) }
// 阶段三 CEM-10（2026-11-15）：我的信用。后端分页参数名是 pageSize，直接拼在 path 里。
// 旧后端无此接口时静默兜底：不报错、不挡「我的活动」页。
async function loadCredit() {
  try {
    const j = await api('/me/credit?page=1&pageSize=50')
    credit.value = { score: j?.score ?? 100 }
    creditEntries.value = pagedItems(j?.entries)
  } catch (_) {
    credit.value = { score: 100 }
    creditEntries.value = []
  }
}
// ===== 阶段四 CEM-09（2026-11-15）：我的申诉 / 举报 =====
async function loadMyGovernance() {
  try { myAppeals.value = pagedItems(await api('/appeals/mine?page=1&pageSize=50')) } catch (_) { myAppeals.value = [] }
  try { myComplaints.value = pagedItems(await api('/complaints/mine?page=1&pageSize=50')) } catch (_) { myComplaints.value = [] }
}
// 详情页举报：活动版传 activity_id，组织者版传 subject_user_id。
async function submitComplaint() {
  if (complaintBusy.value || !detail.value) return
  const category = complaintForm.value.category
  const reason = complaintForm.value.reason.trim()
  if (!category) { showMsg('请选择举报类别'); return }
  if (!reason) { showMsg('请填写举报理由'); return }
  const body = { category, reason }
  if (complaintTarget.value === 'organizer') {
    if (!detail.value.organizer_id) { showMsg('找不到组织者信息，请刷新后重试'); return }
    body.subject_user_id = detail.value.organizer_id
  } else {
    body.activity_id = detail.value.activity_id || detail.value.id
  }
  complaintBusy.value = true
  try {
    await api('/complaints', 'POST', body)
    complaintForm.value = { category: '', reason: '' }
    showMsg('举报已提交，管理员会尽快处理')
  } catch (e) { showMsg(friendlyErr(e)) } finally { complaintBusy.value = false }
}
function focusOrganizerReport() {
  complaintTarget.value = 'organizer'
  showMsg('请在下方「举报」区填写类别与理由后提交')
  nextTick(() => {
    const el = document.getElementById('report-box')
    if (el && el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
}
// 出勤申诉：仅出勤结果已定版（finalized_at 存在）时可提交。
async function submitAttendanceAppeal(d) {
  if (appealBusy.value || !d || !d.my_attendance) return
  if (d.my_attendance.id === undefined || d.my_attendance.id === null) { showMsg('暂无法提交申诉，请刷新后重试'); return }
  const reason = appealForm.value.reason.trim()
  if (!reason) { showMsg('请填写申诉理由'); return }
  appealBusy.value = true
  try {
    const j = await api('/appeals', 'POST', { attendance_id: d.my_attendance.id, reason })
    appealForm.value = { reason: '' }
    showMsg(j && j.duplicate ? '你已提交过该出勤结果的申诉，管理员复核后会通知你' : '申诉已提交，管理员复核后会通知你')
  } catch (e) { showMsg(friendlyErr(e)) } finally { appealBusy.value = false }
}
// ===== 阶段四 CEM-09：账号恢复（未登录可用，查询凭据持久化到 localStorage 'cb_recovery'） =====
function loadRecoveryMine() {
  try {
    const raw = localStorage.getItem('cb_recovery')
    const o = raw ? JSON.parse(raw) : null
    if (!o || typeof o !== 'object' || o.id === undefined || o.id === null) return null
    return { id: o.id, query_token: o.query_token || '' }
  } catch (_) { return null }
}
function saveRecoveryMine(v) {
  try {
    if (v && v.id !== undefined && v.id !== null) localStorage.setItem('cb_recovery', JSON.stringify({ id: v.id, query_token: v.query_token || '' }))
    else localStorage.removeItem('cb_recovery')
  } catch (_) { /* localStorage 不可用时仅保留内存状态 */ }
}
function syncRecoveryQuery() {
  const saved = loadRecoveryMine()
  recoveryMine.value = saved
  if (saved) recoveryQueryForm.value = { id: String(saved.id), query_token: saved.query_token || '' }
}
async function submitRecovery() {
  if (recoveryBusy.value) return
  const f = recoveryForm.value
  const accountText = (f.account || '').trim()
  const reasonText = (f.reason || '').trim()
  if (!accountText) { showMsg('请填写账号'); return }
  if (!reasonText) { showMsg('请填写申请理由'); return }
  recoveryBusy.value = true
  try {
    const j = await api('/recovery', 'POST', {
      account: accountText,
      request_type: Number(f.request_type) === 2 ? 2 : 1,
      reason: reasonText,
      contact: (f.contact || '').trim(),
    })
    if (j && j.id !== undefined && j.id !== null) {
      // duplicate 时后端不重发查询凭据：本机同号旧凭据仍在时保留，避免被空值覆盖。
      const keepToken = j.duplicate && recoveryMine.value && String(recoveryMine.value.id) === String(j.id)
        ? recoveryMine.value.query_token : ''
      const saved = { id: j.id, query_token: j.query_token || keepToken || '' }
      recoveryMine.value = saved
      saveRecoveryMine(saved)
      recoveryQueryForm.value = { id: String(j.id), query_token: saved.query_token || '' }
      recoveryStatusData.value = null
      showMsg(j.duplicate ? '已有待处理的申请，已返回原申请编号；查询凭据不会重复发放' : '申请已提交，请保存申请编号与查询凭据')
    } else { showMsg('申请已提交') }
  } catch (e) { showMsg(friendlyErr(e)) } finally { recoveryBusy.value = false }
}
async function queryRecovery() {
  if (recoveryQueryBusy.value) return
  const id = String(recoveryQueryForm.value.id || '').trim()
  const tk = String(recoveryQueryForm.value.query_token || '').trim()
  if (!id) { showMsg('请填写申请编号'); return }
  if (!tk) { showMsg('请填写查询凭据'); return }
  recoveryQueryBusy.value = true
  try {
    recoveryStatusData.value = await api('/recovery/' + encodeURIComponent(id) + '?query_token=' + encodeURIComponent(tk))
    const saved = { id, query_token: tk }
    recoveryMine.value = saved
    saveRecoveryMine(saved)
  } catch (e) { recoveryStatusData.value = null; showMsg(friendlyErr(e)) } finally { recoveryQueryBusy.value = false }
}
async function useResetCredential() {
  if (resetBusy.value) return
  const credential = (resetForm.value.credential || '').trim()
  const newPassword = resetForm.value.new_password || ''
  if (!credential) { showMsg('请填写重置凭据'); return }
  if (!newPassword) { showMsg('请填写新密码'); return }
  resetBusy.value = true
  try {
    await api('/recovery/reset', 'POST', { credential, new_password: newPassword })
    resetForm.value = { credential: '', new_password: '' }
    recoveryStatusData.value = null
    recoveryMine.value = null
    saveRecoveryMine(null)
    account.value = (recoveryForm.value.account || '').trim()
    password.value = ''
    view.value = 'hall'
    showMsg('密码已重置，请用新密码登录')
  } catch (e) { showMsg(friendlyErr(e)) } finally { resetBusy.value = false }
}
function backToLogin() { recoveryStatusData.value = null; view.value = 'hall' }
// ===== 阶段四 CEM-09：治理工作台 =====
const ADMIN_ACTION_LABEL = {
  COMPLAINT_FILE: '提交举报', COMPLAINT_HANDLE: '处理举报', APPEAL_FILE: '提交申诉', APPEAL_REVIEW: '复核申诉',
  BAN_USER: '封禁用户', UNBAN_USER: '解封用户', DELIST_ACTIVITY: '下架活动', RELIST_ACTIVITY: '恢复活动',
  ADMIN_APPOINT: '任命管理员', ADMIN_REVOKE: '撤销管理员', RECOVERY_SUBMIT: '提交恢复申请',
  RECOVERY_REVIEW: '审核恢复申请', RECOVERY_RESET: '凭据重置密码', CREDIT_REVIEW_HANDLE: '处理信用审查',
}
function adminActionText(a) { return ADMIN_ACTION_LABEL[a] || a || '' }
function impactTitles(list) { return (list || []).map(x => x.title || ('#' + (x.activity_id ?? ''))).join('、') }
// 总览 + 各队列一起拉；单项失败兜底空，不挡其它分区。
async function loadAdmin() {
  if (!user.value || !user.value.is_admin) return
  adminLoading.value = true
  try { adminData.value.overview = await api('/admin/overview') } catch (_) { adminData.value.overview = null }
  try {
    adminData.value.complaints = pagedItems(await api('/admin/complaints?state=PENDING&page=1&pageSize=50'))
      .map(c => ({ ...c, _outcome: 'RESOLVED', _result: '' }))
  } catch (_) { adminData.value.complaints = [] }
  try {
    adminData.value.appeals = pagedItems(await api('/admin/appeals?state=PENDING&page=1&pageSize=50'))
      .map(a => ({ ...a, _outcome: 'UPHOLD', _new_result: 'PRESENT', _result: '' }))
  } catch (_) { adminData.value.appeals = [] }
  try {
    adminData.value.recovery = pagedItems(await api('/admin/recovery?state=PENDING&page=1&pageSize=50'))
      .map(r => ({ ...r, _note: '' }))
  } catch (_) { adminData.value.recovery = [] }
  try {
    adminData.value.creditReviews = pagedItems(await api('/admin/credit-reviews?state=PENDING&page=1&pageSize=50'))
  } catch (_) { adminData.value.creditReviews = [] }
  await loadAdminUsers()
  try {
    adminData.value.bans = pagedItems(await api('/admin/bans?page=1&pageSize=50'))
      .map(b => ({ ...b, _reason: '' }))
  } catch (_) { adminData.value.bans = [] }
  try {
    adminData.value.activities = pagedItems(await api('/admin/activities?page=1&pageSize=50'))
      .map(a => ({ ...a, _reason: '' }))
  } catch (_) { adminData.value.activities = [] }
  try { adminData.value.admins = pagedItems(await api('/admin/admins')) } catch (_) { adminData.value.admins = [] }
  try { adminData.value.actions = pagedItems(await api('/admin/actions?page=1&pageSize=50')) } catch (_) { adminData.value.actions = [] }
  adminLoading.value = false
}
async function loadAdminUsers() {
  try {
    const q = adminUserQuery.value.trim()
    adminData.value.users = pagedItems(await api('/admin/users?q=' + encodeURIComponent(q) + '&page=1&pageSize=50'))
  } catch (_) { adminData.value.users = [] }
}
const adminExtKey = ref(null)
const adminExtForm = ref({ reason: '', days: 7 })
function toggleDeadlineExt(kind, id) {
  const key = kind + '-' + id
  adminExtKey.value = adminExtKey.value === key ? null : key
  adminExtForm.value = { reason: '', days: 7 }
}
async function submitDeadlineExtension(kind, row) {
  if (!row || adminBusyKey.value) return
  const reason = (adminExtForm.value.reason || '').trim()
  const days = Number(adminExtForm.value.days)
  if (!reason) { showMsg('请填写延期原因'); return }
  if (!Number.isInteger(days) || days < 1 || days > 30) { showMsg('延长工作日数须为 1–30 的整数'); return }
  adminBusyKey.value = 'ext-' + kind + '-' + row.id
  try {
    await api('/admin/deadline-extensions', 'POST', { kind, target_id: row.id, reason, extend_workdays: days })
    adminExtKey.value = null
    showMsg('延期已登记')
    await loadAdmin()
  } catch (e) { showMsg(friendlyErr(e)) } finally { adminBusyKey.value = '' }
}
async function handleComplaint(c) {
  if (!c || adminBusyKey.value) return
  const result = (c._result || '').trim()
  if (!result) { showMsg('请填写处理结论'); return }
  adminBusyKey.value = 'complaint-' + c.id
  try {
    await api('/admin/complaints/' + c.id + '/handle', 'POST', { outcome: c._outcome || 'RESOLVED', result })
    showMsg('举报已处理')
    await loadAdmin()
  } catch (e) { showMsg(friendlyErr(e)) } finally { adminBusyKey.value = '' }
}
async function reviewAppeal(a) {
  if (!a || adminBusyKey.value) return
  const outcome = a._outcome || 'UPHOLD'
  const body = { outcome, result: (a._result || '').trim() }
  if (outcome === 'CORRECT') body.new_result = a._new_result || 'PRESENT'
  adminBusyKey.value = 'appeal-' + a.id
  try {
    await api('/admin/appeals/' + a.id + '/review', 'POST', body)
    showMsg(outcome === 'CORRECT' ? '申诉已复核并更正' : '申诉已复核，维持原决定')
    await loadAdmin()
  } catch (e) { showMsg(friendlyErr(e)) } finally { adminBusyKey.value = '' }
}
async function reviewRecovery(r, outcome) {
  if (!r || adminBusyKey.value) return
  adminBusyKey.value = 'recovery-' + r.id
  try {
    const j = await api('/admin/recovery/' + r.id + '/review', 'POST', { outcome, note: (r._note || '').trim() })
    if (outcome === 'APPROVE' && j && j.reset_credential) {
      adminResetCred.value = { reqId: r.id, account: r.account || '', credential: j.reset_credential, expires_at: j.reset_expires_at || '' }
      showMsg('已批准，重置凭据仅显示一次，请立即线下转交申请人')
    } else {
      showMsg(outcome === 'APPROVE' ? '已批准该申请' : '已驳回该申请')
    }
    await loadAdmin()
  } catch (e) { showMsg(friendlyErr(e)) } finally { adminBusyKey.value = '' }
}
async function handleCreditReview(cr, outcome) {
  if (!cr || adminBusyKey.value) return
  adminBusyKey.value = 'credit-' + cr.id
  try {
    await api('/admin/credit-reviews/' + cr.id + '/handle', 'POST', {
      outcome, note: outcome === 'REVIEWED' ? '管理员已审查' : '管理员已忽略',
    })
    showMsg('信用审查已处理')
    await loadAdmin()
  } catch (e) { showMsg(friendlyErr(e)) } finally { adminBusyKey.value = '' }
}
async function openBanImpact(u) {
  if (!u) return
  if (adminBanTarget.value === u.id) { adminBanTarget.value = null; adminBanImpact.value = null; return }
  adminBanTarget.value = u.id
  adminBanImpact.value = null
  adminBanImpactBusy.value = true
  adminBanForm.value = { days: 7, reason: '', future_formal: 'REMOVE', organized: 'CANCEL' }
  try {
    adminBanImpact.value = await api('/admin/users/' + u.id + '/ban-impact')
  } catch (e) {
    showMsg(friendlyErr(e))
    adminBanTarget.value = null
  } finally { adminBanImpactBusy.value = false }
}
async function banUser(u) {
  if (!u || adminBusyKey.value) return
  const days = Number(adminBanForm.value.days)
  if (!(days >= 1 && days <= 30)) { showMsg('封禁期限须为 1 至 30 日'); return }
  const reason = (adminBanForm.value.reason || '').trim()
  if (!reason) { showMsg('请填写封禁原因'); return }
  if (!confirm(`确认封禁「${u.nickname || u.account}」${days} 日？`)) return
  adminBusyKey.value = 'ban-' + u.id
  try {
    await api('/admin/users/' + u.id + '/ban', 'POST', {
      days, reason,
      future_formal: adminBanForm.value.future_formal,
      organized: adminBanForm.value.organized,
    })
    showMsg('已封禁该用户')
    adminBanTarget.value = null
    adminBanImpact.value = null
    await loadAdmin()
  } catch (e) { showMsg(friendlyErr(e)) } finally { adminBusyKey.value = '' }
}
async function unbanUser(b) {
  if (!b || adminBusyKey.value) return
  const reason = (b._reason || '').trim()
  if (!reason) { showMsg('请填写解封原因'); return }
  if (!confirm(`确认解封「${b.nickname || b.account}」？`)) return
  adminBusyKey.value = 'unban-' + b.user_id
  try {
    await api('/admin/users/' + b.user_id + '/unban', 'POST', { reason })
    showMsg('已解封该用户')
    await loadAdmin()
  } catch (e) { showMsg(friendlyErr(e)) } finally { adminBusyKey.value = '' }
}
async function delistActivity(a) {
  if (!a || adminBusyKey.value) return
  const reason = (a._reason || '').trim()
  if (!reason) { showMsg('请填写下架原因'); return }
  if (!confirm(`确认下架活动「${a.title}」？进行中的活动会被取消。`)) return
  adminBusyKey.value = 'act-' + a.id
  try {
    await api('/admin/activities/' + a.id + '/delist', 'POST', { reason })
    showMsg('活动已下架')
    await loadAdmin()
  } catch (e) { showMsg(friendlyErr(e)) } finally { adminBusyKey.value = '' }
}
async function relistActivity(a) {
  if (!a || adminBusyKey.value) return
  const reason = (a._reason || '').trim()
  if (!reason) { showMsg('请填写恢复展示原因'); return }
  adminBusyKey.value = 'act-' + a.id
  try {
    await api('/admin/activities/' + a.id + '/relist', 'POST', { reason })
    showMsg('活动已恢复展示')
    await loadAdmin()
  } catch (e) { showMsg(friendlyErr(e)) } finally { adminBusyKey.value = '' }
}
// DG-ADM-01（2026-11-20）：出勤名单只读展示与组织者本人核对（SDD §6.9）。
// 组织者字段以 organizer_id 为准，兼容 organizerId；名单行的 user_id 可能是数字或字符串。
function isAdminOrganizerRow(a, r) {
  if (!a || !r) return false
  const organizerId = a.organizer_id ?? a.organizerId
  if (organizerId === null || organizerId === undefined || organizerId === '') return false
  return String(r.user_id) === String(organizerId)
}
function adminAttResultText(r) {
  const result = r && r.result
  if (result === 'PRESENT') return '到场'
  if (result === 'ABSENT_VERIFIED') return '核实缺席'
  if (result === 'EXEMPT') return '豁免'
  if (result === 'UNVERIFIED') return '未核实'
  return '未核对'
}
function adminAttCheckinAt(r) {
  if (!r) return null
  return r.checked_in_at || r.checkin_at || r.checkin_time || null
}
// 出勤名单加载只被 toggleAdminAttendance 与提交成功后的刷新调用；
// seq 与当前展开的活动同时校验，快速切换/收起时的迟到响应一律丢弃。
async function loadAdminAttendance(id, seq) {
  if (seq !== adminAttSeq || adminAttOpenId.value !== id) return
  adminAttRows.value = []
  adminAttError.value = ''
  adminAttLoading.value = true
  try {
    const res = await api('/admin/activities/' + id + '/attendance?page=1&pageSize=100')
    if (seq !== adminAttSeq || adminAttOpenId.value !== id) return
    const items = pagedItems(res)
    adminAttRows.value = (Array.isArray(items) ? items : [])
      .map(r => ({ ...r, _result: r.result || 'UNVERIFIED', _evidence: '' }))
  } catch (e) {
    if (seq !== adminAttSeq || adminAttOpenId.value !== id) return
    adminAttError.value = (e && e.message) || '加载失败'
  } finally {
    if (seq === adminAttSeq && adminAttOpenId.value === id) adminAttLoading.value = false
  }
}
async function toggleAdminAttendance(a) {
  if (!a) return
  const id = a.id
  if (adminAttOpenId.value === id) {
    adminAttOpenId.value = null
    adminAttSeq++
    adminAttRows.value = []
    adminAttError.value = ''
    adminAttLoading.value = false
    return
  }
  const seq = ++adminAttSeq
  adminAttOpenId.value = id
  await loadAdminAttendance(id, seq)
}
async function submitOrganizerAttendance(a) {
  if (!a || adminBusyKey.value) return
  const id = a.id
  if (adminAttOpenId.value !== id) return
  const row = adminAttRows.value.find(r => isAdminOrganizerRow(a, r))
  if (!row) { showMsg('名单中未找到组织者本人的出勤记录'); return }
  const seq = adminAttSeq
  adminBusyKey.value = 'admin-att-org-' + id
  try {
    await api('/admin/activities/' + id + '/attendance/organizer', 'POST', {
      result: row._result, evidence: row._evidence,
    })
    // 提交期间切换活动或收起面板：不刷新、不弹提示，避免覆盖当前面板或复活已收起的面板。
    if (seq !== adminAttSeq || adminAttOpenId.value !== id) return
    showMsg('组织者出勤已核对')
    await loadAdminAttendance(id, seq)
  } catch (e) {
    // 后端对已定版等业务错误有明确文案，原样提示（后端是最终权威）。
    if (seq === adminAttSeq && adminAttOpenId.value === id) showMsg((e && e.message) || friendlyErr(e))
  } finally {
    if (adminBusyKey.value === 'admin-att-org-' + id) adminBusyKey.value = ''
  }
}
async function appointAdmin() {
  const userId = String(adminAppointForm.value.user_id || '').trim()
  if (!userId) { showMsg('请填写要任命的用户 ID'); return }
  try {
    await api('/admin/admins', 'POST', { user_id: userId, note: (adminAppointForm.value.note || '').trim() })
    showMsg('已任命为管理员')
    adminAppointForm.value = { user_id: '', note: '' }
    await loadAdmin()
  } catch (e) { showMsg(friendlyErr(e)) }
}
async function revokeAdmin(ad) {
  if (!ad) return
  const reason = prompt(`撤销「${ad.nickname || ad.account}」管理员权限的原因：`, '')
  if (reason === null) return
  const text = reason.trim()
  if (!text) { showMsg('请填写撤销原因'); return }
  try {
    await api('/admin/admins/' + ad.user_id + '/revoke', 'POST', { reason: text })
    showMsg('已撤销该管理员')
    await loadAdmin()
  } catch (e) { showMsg(friendlyErr(e)) }
}
async function loadNotif() {
  notifPage.value = 0
  try {
    const p = pageQuery()
    const j = await api('/notifications?' + p.toString())
    notifs.value = pagedItems(j)
    notifTotal.value = (j && typeof j.total === 'number') ? j.total : notifs.value.length
    notifPage.value = pageOf(j, 1)
    const u = j && (j.unread ?? j.unread_count)
    unread.value = typeof u === 'number' ? u : notifs.value.filter(n => !n.read_at).length
    notifHasMore.value = pagedHasMore(j, notifs.value.length)
    notifError.value = ''
  } catch (e) { notifError.value = friendlyErr(e); notifs.value = [] }
}
// 通知分页加载更多（2026-11-15 规格）：追加下一页并按 id 去重，未读数沿用首屏值。
async function loadMoreNotif() {
  if (notifMoreBusy.value || !notifHasMore.value) return
  notifMoreBusy.value = true
  try {
    const next = notifPage.value + 1
    const j = await api('/notifications?' + pageQuery(next).toString())
    const items = pagedItems(j)
    const seen = new Set(notifs.value.map(n => n.id))
    notifs.value = notifs.value.concat(items.filter(n => !seen.has(n.id)))
    notifPage.value = next
    notifHasMore.value = items.length > 0 && pagedHasMore(j, notifs.value.length)
  } catch (e) { showMsg(friendlyErr(e)) } finally { notifMoreBusy.value = false }
}
async function readAll() {
  try { await api('/notifications/read-all', 'POST'); unread.value = 0; await loadNotif() } catch (e) { showMsg(friendlyErr(e)) }
}
// 2026-11-15 规格：点击单条通知即标为已读（本地先行更新，失败回滚）。
// 通知页导流：先按既有语义标为已读，再切到「我的活动 · 候补」分区（不做接受/拒绝）。
// G19（2026-11-20）：补齐通知目标跳转链——定位到对应参与记录卡片并高亮；找不到时给出失效说明。
function notifInvitationActive(n) {
  return n.type === '邀请' && (n.invitation_status == null || n.invitation_status === 'PENDING')
    && inviteCountdownText(n) !== '已过期'
}
async function viewWaitingFromNotif(n) {
  if (!n || n.activity_id == null) return
  void readOne(n)
  myTab.value = 'waiting'
  go('my', { load: false })
  const c = membershipContext(n.activity_id)
  const matches = p => String(p.activity_id) === String(n.activity_id) && !queueClosed(p)
    && (n.type === '邀请'
      ? p.status === 'INVITED' && p.invitation_id != null && inviteSecondsLeft(p.invitation_expires_at) !== null
        && (n.invitation_id == null || String(p.invitation_id) === String(n.invitation_id))
      : ['WAITING', 'INVITED'].includes(p.status))
  let ok = await loadMy()
  if (!currentMembershipContext(c)) return
  let target = mine.value.find(matches)
  // 目标可能在第101条以后；只在成功推进页码后继续，不用首批缺失宣告失效。
  while (ok && !target && myHasMore.value) {
    const before = myPage.value
    ok = await loadMoreMy()
    if (!currentMembershipContext(c)) return
    if (myPage.value <= before) { ok = false; break }
    target = mine.value.find(matches)
  }
  if (!currentMembershipContext(c)) return
  if (!ok) {
    notifInviteMissing.value = { activityId: n.activity_id, error: true, notification: n }
  } else if (target && (n.type !== '邀请' || notifInvitationActive(n))) {
    highlightPartId.value = target.id
    await nextTick()
    const el = document.querySelector('[data-part-id="' + target.id + '"]')
    if (el) { el.focus({ preventScroll: true }); el.scrollIntoView({ behavior: 'smooth', block: 'center' }) }
  } else {
    notifInviteMissing.value = { activityId: n.activity_id, error: false }
  }
}
// G19：通知卡片「查看活动」入口——标读后直接打开对应活动详情。
function viewActivityFromNotif(n) {
  readOne(n)
  if (n && n.activity_id != null) openDetail(n.activity_id)
}
// 2026-11-17：详情页候补状态卡的就近入口（跳到「我的活动 · 候补」页签）。
function viewMyWaiting() { myTab.value = 'waiting'; go('my') }
async function readOne(n) {
  if (!n || n.read_at) return
  const prev = n.read_at, sessionToken = token.value
  n.read_at = new Date().toISOString()
  unread.value = Math.max(0, unread.value - 1)
  try {
    await api('/notifications/' + n.id + '/read', 'POST')
  } catch (e) {
    if (token.value !== sessionToken) return
    n.read_at = prev
    unread.value++
    showMsg(friendlyErr(e))
  }
}
// G04：取消仅限未结束/未取消，原因必填、最多 495 码点（服务端 detail 留「取消原因：」5 字）。
const cancelDrafts = new Map()
function canCancelActivity(d, at = nowTick.value) {
  if (!user.value || !d || !d.roster) return false
  const stage = d.activity_status || d.status
  return !['CANCELLED', 'ENDED'].includes(stage) && !(d.end_time && parseShanghai(d.end_time) <= at)
}
function cancelActivity(id) {
  if (actLocked('act-' + id) || cardActionLocked(id)) return
  const c = membershipContext(id)
  const d = detail.value && (detail.value.id === id || detail.value.activity_id === id) ? detail.value : null
  if (!canCancelActivity(d)) { showMsg('活动已结束或已取消，不能再取消'); return }
  const pending = (d.pending_invitations || []).length
  let text = `取消后将通知 ${d.formal ?? 0} 名正式成员与 ${d.waiting ?? 0} 名候补成员，参与记录转为已取消。`
  if (pending > 0) text += `另有 ${pending} 名成员的待确认邀请将随活动取消而作废，他们也会收到通知。`
  const input = { label: '取消原因（必填）', value: cancelDrafts.get(String(id)) || '', maxLength: 495, required: true }
  showConfirmModal('取消活动', text, {
    input, confirmLabel: '确认取消活动', cancelLabel: '返回',
    onClose: () => { if (c.token === token.value && c.owner === user.value?.id) cancelDrafts.set(String(id), input.value.trim()) },
    onConfirm: (reason) => doCancelActivity(id, reason, c),
  })
}
async function doCancelActivity(id, reason, c) {
  reason = String(reason || '').trim()
  if (!currentMembershipContext(c) || view.value !== 'detail'
      || String(detail.value?.activity_id || detail.value?.id) !== String(id)
      || !canCancelActivity(detail.value, calibratedNow()) || !reason || [...reason].length > 495) return
  const unlock = lockActionKeys(['act-' + id, 'member-' + id])
  if (!unlock) return
  cancelDrafts.set(String(id), reason)
  try {
    const j = await postRetryable('/activities/' + id + '/cancel', { reason, confirmed: true })
    if (!currentMembershipContext(c)) return
    cancelDrafts.delete(String(id))
    // 原地更新状态及名单，不用会导航的 openDetail，亦不让旧响应抢回页面。
    await refreshCurrentDetail(id)
    if (!currentMembershipContext(c)) return
    if (j?.alreadyCancelled) showMsg('活动已取消')
    else if (typeof j?.notified === 'number') showMsg(`活动已取消，已通知 ${j.notified} 人`)
    else showMsg('活动已取消，请以重新查询的状态为准')
    void loadHall()
  } catch (e) {
    if (!currentMembershipContext(c)) return
    await refreshCurrentDetail(id)
    if (!currentMembershipContext(c)) return
    // 保留原草稿和不确定请求键；只有用户再次明确确认才重试写入。
    showMsg((isUncertainErr(e) ? '结果暂不确定：' : '取消未完成：') + friendlyErr(e) + '；已重新查询状态并保留原因')
  } finally { unlock() }
}
async function focusPublishError() {
  await nextTick()
  document.querySelector('.publish-form [aria-invalid="true"]')?.focus()
}
async function publish() {
  if (publishBusy.value || view.value !== 'publish') return
  const c = membershipContext(null)
  publishBusy.value = true
  try {
    // 2026-11-20：发布前一次性按字段校验，错误写进字段槽（模板已绑定），全部通过才发请求。
    publishErrors.value = { title: '', category: '', location: '', capacity: '', description: '', conditions: '' }
    dtErrors.value = { deadline: '', start_time: '', end_time: '' }
    const title = String(form.value.title ?? '').trim()
    if (!title) publishErrors.value.title = '标题不能为空'
    if ([...title].length > 50) publishErrors.value.title = '标题不能超过 50 字'
    // 任务 10（2026-11-14）：类别必须显式选择（默认「请选择」），未选不发请求。
    if (!form.value.category) publishErrors.value.category = '请选择类别'
    const location = String(form.value.location ?? '').trim()
    if (!location) publishErrors.value.location = '地点不能为空'
    if ([...location].length > 100) publishErrors.value.location = '地点不能超过 100 字'
    const cap = form.value.capacity
    const capNum = typeof cap === 'number' ? cap : Number(cap)
    if (cap === '' || cap === null || cap === undefined || !Number.isInteger(capNum) || capNum < 1 || capNum > 100) {
      publishErrors.value.capacity = '人数上限需为 1-100 的整数'
    }
    if ([...String(form.value.description ?? '')].length > 2000) publishErrors.value.description = '介绍不能超过 2000 字'
    if ([...String(form.value.conditions ?? '')].length > 500) publishErrors.value.conditions = '参与条件不能超过 500 字'
    // 任务 12/2026-11-18 任务 11：三处时间逐栏校验，空值与格式错分开报，写进 dtErrors。
    const dtLabels = { deadline: '报名截止', start_time: '开始时间', end_time: '结束时间' }
    for (const k of ['deadline', 'start_time', 'end_time']) {
      const raw = String(form.value[k] ?? '').trim()
      if (!raw) { dtErrors.value[k] = `${dtLabels[k]}不能为空`; continue }
      if (!toApiDT(raw)) dtErrors.value[k] = `${dtLabels[k]}格式不对，请用「年-月-日 时:分」填写`
    }
    const deadline = toApiDT(form.value.deadline)
    const start = toApiDT(form.value.start_time)
    const end = toApiDT(form.value.end_time)
    // 三栏格式都合法时才校验先后顺序：现在 < 报名截止 ≤ 开始 < 结束
    //（parseShanghai 返回 UTC 毫秒，与 Date.now() 同口径，可直接比较）。
    if (!dtErrors.value.deadline && !dtErrors.value.start_time && !dtErrors.value.end_time) {
      const tDeadline = parseShanghai(deadline)
      const tStart = parseShanghai(start)
      const tEnd = parseShanghai(end)
      if (!(tDeadline > calibratedNow() && tDeadline <= tStart && tStart < tEnd)) {
        dtErrors.value.start_time = '时间需满足：现在 < 报名截止 ≤ 开始 < 结束'
      }
    }
    if (Object.values(publishErrors.value).some(Boolean) || Object.values(dtErrors.value).some(Boolean)) {
      msg.value = '请按字段旁的提示修改后再发布'
      await focusPublishError()
      return
    }
    // 任务 22：标题星期与开始星期不符，非阻塞确认（点取消可回去改）。
    // 任务 23：同名标题非阻塞提醒（不拦截入库，点取消可回去改）。
    const warns = []
    if (titleWeekdayHint.value) warns.push(titleWeekdayHint.value)
    if (form.value.title.trim() && hall.value.some(a => a.title === form.value.title.trim())) warns.push(`已有同名活动「${form.value.title.trim()}」，确认要再发一个吗？第二场请在标题注明场次`)
    if (warns.length && !confirm(warns.join('\n'))) return
    // 2026-11-17：封面只在明确选了图库/上传时带 cover_url；默认轮换不带该键。
    const j = await api('/activities', 'POST', {
      ...form.value, deadline, start_time: start, end_time: end,
      cover_url: selectedCover.value || undefined,
    })
    if (!currentMembershipContext(c)) return
    showMsg('发布成功' + (j?.id ? '，活动编号 ' + j.id : '') + '，记得给自己报名占一个名额（组织者报名计入正式名额）。想报名的同学可通过详情页留言联系你（仅你可见）')
    // 任务 23：发完清空表单（恢复空态，类别回默认值「请选择」）。
    form.value = { title: '', category: '', location: '', capacity: 4, deadline: '', start_time: '', end_time: '', description: '', conditions: '' }
    // 任务 16（2026-11-19）：时间栏就地报错一并清空。
    dtErrors.value = { deadline: '', start_time: '', end_time: '' }
    publishErrors.value = { title: '', category: '', location: '', capacity: '', description: '', conditions: '' }
    // 封面状态一并回默认，避免下一次发布沿用上一张图。
    coverChoice.value = 'default'; coverGallery.value = ''; coverUploaded.value = ''; coverUploadError.value = ''
    view.value = 'hall'; loadHall()
    // 任务 8（2026-11-13）：从页面底部提交后切回大厅，渲染完成后回到页顶，发布成功横幅才可见。
    await nextTick()
    window.scrollTo(0, 0)
  } catch (e) {
    if (!currentMembershipContext(c)) return
    const errors = e.data?.fieldErrors
    if (errors && typeof errors === 'object') {
      for (const key of Object.keys(publishErrors.value)) if (typeof errors[key] === 'string') publishErrors.value[key] = errors[key]
      for (const key of Object.keys(dtErrors.value)) if (typeof errors[key] === 'string') dtErrors.value[key] = errors[key]
    }
    msg.value = friendlyErr(e)
    await focusPublishError()
  } finally { publishBusy.value = false }
}
// 任务 2：改时间入口（组织者视角，仅报名截止前）。预填当前时间（显示格式）。
function openReschedule(d) {
  if (d.status !== 'OPEN' || deadlinePassed(d, calibratedNow())) return
  activityEditId.value = null
  rescheduleForm.value = {
    deadline: parseDTInput(d.deadline) || '',
    start_time: parseDTInput(d.start_time) || '',
    end_time: parseDTInput(d.end_time) || '',
    // G24：草稿归属当前活动（列表项可能是参与记录，优先取 activity_id）。
    activityId: d.activity_id || d.id,
  }
  rescheduleErrors.value = { deadline: '', start_time: '', end_time: '' }
  rescheduleOpen.value = true
}
function openActivityEditor(d) {
  if (d.status !== 'OPEN' || deadlinePassed(d, calibratedNow())) return
  rescheduleOpen.value = false
  activityEditId.value = d.activity_id || d.id
}
async function saveActivityEdit(id, payload) {
  if (view.value !== 'detail' || String(detail.value?.activity_id || detail.value?.id) !== String(id)
    || String(activityEditId.value || rescheduleForm.value.activityId) !== String(id)) throw new Error('编辑草稿已失效，请重新打开')
  if (detail.value.status !== 'OPEN' || deadlinePassed(detail.value, calibratedNow())) throw new Error('已过可编辑阶段，请刷新活动状态')
  return postRetryable('/activities/' + id + '/edit', payload)
}
async function onActivityEdited(result) {
  const id = result.activity_id || result.id, c = membershipContext(id)
  activityEditId.value = null; rescheduleOpen.value = false
  await refreshCurrentDetail(id)
  if (!currentMembershipContext(c)) return
  // G02：按 edit 回执给结果提示（扩容/受影响人数），无回执字段时用通用文案。
  if (result && result.capacity_increased) showMsg(`活动已修改，容量已扩大，已通知 ${result.affected_count ?? 0} 人，请以重新查询的详情为准`)
  else if (result && typeof result.affected_count === 'number' && result.affected_count > 0) showMsg(`活动已修改，已通知 ${result.affected_count} 人，请以重新查询的详情为准`)
  else showMsg('活动已修改，请以重新查询的详情为准')
  loadHall()
}
// 任务 9：站内留言——详情页给组织者留言（报名前后均可，仅组织者可见）。
async function sendMessage(id) {
  const content = messageDraft.value.trim()
  if (!content) { msg.value = '留言内容不能为空'; return }
  try {
    await api('/activities/' + id + '/messages', 'POST', { content })
    messageDraft.value = ''
    // 任务 17（2026-11-10）：发完刷新详情（新留言进「我发过的留言」区），
    // 再置提示（openDetail 会清空 msg，须在它之后设置）。
    try { await openDetail(id) } catch (_) {}
    showMsg('留言已发送，组织者会看到')
  } catch (e) { msg.value = friendlyErr(e) }
}
// 任务 9：组织者在名单视图回一条留言（每条留言只能回一条，后端校验）。
async function replyMessage(activityId, mid) {
  const content = (replyDrafts.value[mid] || '').trim()
  if (!content) { msg.value = '回复内容不能为空'; return }
  try {
    await api(`/activities/${activityId}/messages/${mid}/reply`, 'POST', { content })
    showMsg('回复已发送，留言人会收到通知')
    if (view.value === 'roster') {
      await openRoster(activityId)
    } else if (view.value === 'detail' && detail.value) {
      try { await openDetail(activityId) } catch (_) {}
    }
  } catch (e) { msg.value = friendlyErr(e) }
}
// 任务 10：改密码（POST /api/me/password；成功后当前 token 即刻失效，须重新登录）。
async function changePassword() {
  if (pwBusy.value) return
  pwBusy.value = true
  try {
    await api('/me/password', 'POST', { old_password: pwForm.value.oldPw, new_password: pwForm.value.newPw })
    pwForm.value = { oldPw: '', newPw: '' }
    msg.value = '密码已修改，请重新登录'
    // 任务 9：改密成功后清空密码框，再清 token。
    password.value = ''
    token.value = ''; localStorage.removeItem('token'); user.value = null
    clearAccountState(); view.value = 'hall'
  } catch (e) { msg.value = friendlyErr(e) } finally { pwBusy.value = false }
}
async function resetDemo() { if (!confirm('确认恢复演示数据吗？当前业务数据会被清空。')) return; await api('/demo/reset', 'POST'); msg.value = '演示数据已恢复'; loadHall() }
function go(v, { load = true } = {}) {
  navigationSeq++
  queueRefreshAt = calibratedNow()
  membershipNotice.value = null
  // G24：导航离开（含详情尚在加载时）立即废弃在途详情响应。
  detailSeq++
  // 2026-11-21：抽屉内点导航后收起并把焦点交还菜单按钮，避免焦点留在不可见抽屉里。
  if (menuOpen.value) closeDrawer(); else menuOpen.value = false
  // 任务 14：切页清除提示条（报名提示 5 秒自动消失，退出提示 15 秒；换页即清，行为与登录横幅一致）。
  msgSeq++; msg.value = ''; withdrawNotice.value = null
  acceptSuccess.value = null
  highlightPartId.value = null
  notifInviteMissing.value = null
  // G24：离开详情（切页）时无条件关闭编辑面板并清空草稿（含绑定活动 id）。
  activityEditId.value = null
  detailRefreshing.value = false
  rescheduleOpen.value = false
  rescheduleForm.value = { deadline: '', start_time: '', end_time: '', activityId: null }
  view.value = v
  // 任务 8（2026-11-13）：切页回到页顶，与 openDetail 已有行为一致。
  nextTick(() => window.scrollTo(0, 0))
  if (!load) return
  if (v === 'my') { loadMy(); loadOrganized(); loadCredit(); loadMyGovernance() } if (v === 'notif') loadNotif()
  if (v === 'admin') loadAdmin()
  if (v === 'recovery') syncRecoveryQuery()
  if (v === 'hall') {
    // 任务 13（2026-11-14）：返回大厅时重置筛选项，避免从详情页回来仍停在旧筛选上。
    q.value = ''; category.value = ''; timeSlot.value = ''; campus.value = ''
    loadHall()
  }
}
// G01：离页与账号/会话切换同步废弃读写世代，包含不经 go() 的详情/登录导航。
watch(view, (next, previous) => {
  if (previous === 'profile' && next !== 'profile') invalidateProfile()
}, { flush: 'sync' })
watch([() => user.value?.id, token], () => invalidateProfile(), { flush: 'sync' })
// 2026-11-17：移动抽屉打开时锁定 body 滚动、挂 dialog 语义并把焦点移入首项；关闭时还原。
watch(menuOpen, (open) => {
  if (open && isMobileDrawer()) {
    document.body.style.overflow = 'hidden'
    const nav = mobileNav.value
    if (nav) { nav.setAttribute('role', 'dialog'); nav.setAttribute('aria-modal', 'true') }
    nextTick(() => {
      const el = mobileNav.value
      const first = el && el.querySelector('button')
      if (first) first.focus()
    })
  } else {
    const nav = mobileNav.value
    if (nav) { nav.removeAttribute('role'); nav.removeAttribute('aria-modal') }
    if (!authModal.value.visible) document.body.style.overflow = ''
  }
})
// 2026-11-17：登录/注册页原本走顶部提示条的结果型反馈，统一改走居中浮层。
// 登录/注册成功横幅出现时 user 已落盘，watcher 提前返回，不会在切页瞬间闪浮层。
watch([msg, view, user], () => {
  if (!msg.value) return
  if (!isAuthViewNow()) return
  if (authModal.value.visible) return
  const text = msg.value
  const title = view.value === 'register'
    ? '注册失败'
    : (/密码已修改|密码已重置/.test(text) ? '提示'
      : (/账号或密码错误/.test(text) ? '登录失败' : '提示'))
  msg.value = ''
  showAuthModal(title, text, null)
})
// 任务 18：每秒检查一次递补邀请是否过期；过期后自动刷新为已过期/已顺延态，
// 不再显示可点的接受/拒绝按钮（每活动只触发一次，避免每秒重复拉取）。
watch(nowTick, () => {
  // G14：仅在相关页可见且无写入时原地刷新候补快照，不把本地时钟当终态写回。
  if (user.value && !document.hidden && nowTick.value - queueRefreshAt >= 15000
    && !signupLocked.value && !actionBusy.value.size && !authModal.value.visible) {
    queueRefreshAt = nowTick.value
    if (view.value === 'detail' && ['WAITING', 'INVITED'].includes(detail.value?.my_status) && !detailRefreshing.value) {
      void refreshCurrentDetail(detail.value.activity_id || detail.value.id)
    } else if (view.value === 'my' && myTab.value === 'waiting' && !myMoreBusy.value) {
      void refreshLoadedMy()
    }
  }
  const expired = mine.value.filter(p => p.status === 'INVITED' && p.invitation_expires_at
    && parseShanghai(p.invitation_expires_at) <= nowTick.value
    && !expiredRefreshed.value.has(p.activity_id))
  if (expired.length) {
    expired.forEach(p => expiredRefreshed.value.add(p.activity_id))
    loadMy()
    // sweep 每 10 秒跑一次，12 秒后再拉一次，把已顺延的 EXPIRED 状态也刷回来。
    setTimeout(() => loadMy(), 12000)
  }
  // 详情页的邀请过期才刷新详情（2026-11-10：openDetail 会切到详情页，不在详情页时别把用户拽过去）。
  if (view.value === 'detail' && detail.value && detail.value.invitation_id && detail.value.invitation_expires_at
    && parseShanghai(detail.value.invitation_expires_at) <= nowTick.value
    && !expiredRefreshed.value.has('detail-' + (detail.value.activity_id || detail.value.id))) {
    expiredRefreshed.value.add('detail-' + (detail.value.activity_id || detail.value.id))
    openDetail(detail.value.activity_id || detail.value.id).catch(() => {})
  }
  // 阶段二 CEM-08：组织者视角签到码到期自动重拉（详情仍打开、活动仍在进行中）。
  if (view.value === 'detail' && detail.value && detail.value.roster
    && detail.value.status === 'RUNNING' && checkinCode.value && !checkinFetching.value
    && (typeof checkinCode.value.seconds_left === 'number' || checkinCode.value.window_end)
    && checkinSecondsLeft.value <= 0) {
    loadCheckinCode(detail.value.activity_id || detail.value.id)
  }
})
onMounted(async () => {
  // 2026-11-17：Esc 关闭浮层/抽屉，抽屉打开时 Tab 焦点圈定在抽屉内。
  document.addEventListener('keydown', onDocKeydown)
  // 2026-11-21：旋到桌面宽度时收起抽屉，避免 aria-modal 残留在已隐藏的导航上。
  if (window.matchMedia) {
    drawerMq = window.matchMedia('(min-width: 641px)')
    drawerMq.addEventListener('change', onDrawerBreakpointChange)
  }
  // 任务 8/18：每秒刷新时钟，驱动倒计时显示。
  tickTimer = setInterval(() => { nowTick.value = calibratedNow() }, 1000)
  // 任务 9：刷新后保持深色偏好（localStorage 'theme'）。
  applyTheme()
  // 任务 4：地址带 ?demo=1 时开启演示模式（页脚恢复入口出现），写入 localStorage。
  if (new URLSearchParams(location.search).get('demo') === '1') {
    demoMode.value = true; localStorage.setItem('demoMode', '1')
  }
  // 未登录只见登录页，不拉大厅数据；带 token 才恢复登录并拉大厅（2026-11-10）。
  if (token.value) {
    loadHall()
    // 任务 3：刷新页面带 token 恢复登录时，未读数也要立即是当前账号的，
    // 不能等到手动点「通知」才刷。
    try { const j = await api('/me'); user.value = j.user; loadNotif() } catch { logout() }
  } else {
    // 任务 2：未登录时只拉公开大厅数据，供登录页底部摘要显示。
    loadLoginHall()
  }
})
onUnmounted(() => {
  if (tickTimer) clearInterval(tickTimer)
  if (drawerMq) drawerMq.removeEventListener('change', onDrawerBreakpointChange)
  document.removeEventListener('keydown', onDocKeydown)
})
</script>
