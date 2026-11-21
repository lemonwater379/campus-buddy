package com.campusbuddy.service;

import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.stereotype.Service;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/** DG-BE-02：密码散列（PBKDF2，禁止明文）+ 持久化会话（仅存令牌哈希）。 */
@Service
public class AuthService {
    /** A2a 序号1：同账号连续密码失败 5 次锁定 10 分钟（账号不存在不计）。 */
    private static final int MAX_LOGIN_FAILURES = 5;
    private static final long LOGIN_LOCK_MILLIS = 10 * 60 * 1000L;
    /** DG-BE-02：默认空闲 30 分钟、绝对 12 小时到期；最近访问时间每分钟最多写一次。 */
    private static final long SESSION_IDLE_MILLIS = Long.getLong("campus.session.idleMillis", 30 * 60 * 1000L);
    private static final long SESSION_ABSOLUTE_MILLIS = Long.getLong("campus.session.absoluteMillis", 12 * 60 * 60 * 1000L);
    private static final long SESSION_TOUCH_MILLIS = 60_000;

    private final JdbcTemplate jdbc;
    private volatile boolean sessionTableReady;
    /** 按账号保存连续失败计数与锁定截止；compute 保证同账号并发不丢计数。 */
    private final Map<String, LoginFailure> loginFailures = new ConcurrentHashMap<>();

    private record LoginFailure(int count, long lockedUntil) { }

    public AuthService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    /** DG-BE-02：首次访问会话表时建表；建表失败不标记成功，下次调用重试。 */
    private void ensureSessionTable() {
        if (sessionTableReady) return;
        synchronized (this) {
            if (sessionTableReady) return;
            try {
                jdbc.execute("""
                        CREATE TABLE IF NOT EXISTS auth_session (
                            token_hash VARCHAR(64) PRIMARY KEY,
                            user_id BIGINT NOT NULL,
                            created_at BIGINT NOT NULL,
                            last_access_at BIGINT NOT NULL
                        )
                        """);
            } catch (DataAccessException e) {
                System.err.println("DG-BE-02：auth_session 建表失败，下次访问重试：" + e.getMessage());
                return;
            }
            try {
                jdbc.execute("CREATE INDEX idx_auth_session_user ON auth_session(user_id)");
            } catch (DataAccessException ignored) {
                // DG-BE-02：MySQL 不支持 CREATE INDEX IF NOT EXISTS；索引失败不影响会话表使用。
            }
            sessionTableReady = true;
        }
    }

    private static String hashSessionToken(String token) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(token.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("运行环境不支持 SHA-256", e);
        }
    }

    public static String hash(String password) {
        try {
            byte[] salt = new byte[16];
            new SecureRandom().nextBytes(salt);
            byte[] dk = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
                    .generateSecret(new PBEKeySpec(password.toCharArray(), salt, 100000, 256)).getEncoded();
            return HexFormat.of().formatHex(salt) + ":" + HexFormat.of().formatHex(dk);
        } catch (Exception e) { throw new RuntimeException(e); }
    }

    public static boolean verify(String password, String stored) {
        try {
            String[] parts = stored.split(":");
            byte[] salt = HexFormat.of().parseHex(parts[0]);
            byte[] dk = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
                    .generateSecret(new PBEKeySpec(password.toCharArray(), salt, 100000, 256)).getEncoded();
            // 恒定时间比较，避免用 String.equals 因提前返回泄露前缀信息。
            return java.security.MessageDigest.isEqual(dk, HexFormat.of().parseHex(parts[1]));
        } catch (Exception e) { return false; }
    }

    public String login(String account, String password) {
        // H1-1：null/空白账号或 null 密码不触碰内存计数字典，按既有认证失败路径返回。
        if (account == null || account.isBlank() || password == null) return null;
        // A2a 序号1：锁定检查先于密码核验，锁定期间正确密码也拒绝。
        requireNotLocked(account);
        var rows = jdbc.queryForList(
                "SELECT id, password_hash, status, account FROM app_user WHERE account = ?", account);
        // 账号不存在不计数，保持原有“账号或密码错误”口径。
        if (rows.isEmpty()) return null;
        var row = rows.get(0);
        if (!"ACTIVE".equals(row.get("status"))) return null;
        // #8 复核-b：按数据库中的账号名复检与计数，避免同一账号因输入大小写不同而分开计数。
        String canonical = (String) row.get("account");
        requireNotLocked(canonical);
        if (!verify(password, (String) row.get("password_hash"))) {
            // 只对“账号存在且密码错误”计数；并发同账号由 ConcurrentHashMap.compute 串行化。
            recordLoginFailure(canonical);
            requireNotLocked(canonical);
            return null;
        }
        // 阶段四 CEM-09（2026-11-15）：密码校验通过后再查封禁，避免向密码错误者泄露封禁状态。
        // 封禁异常发生在正确密码之后，不增加失败计数。
        var bans = jdbc.queryForList(
                "SELECT reason, expires_at FROM user_ban WHERE user_id=? AND lifted_at IS NULL",
                row.get("id"));
        if (!bans.isEmpty()) {
            Object reason = bans.get(0).get("reason");
            Object expiresAt = bans.get(0).get("expires_at");
            throw new IllegalStateException("账号已被封禁：" + reason + "（至 " + expiresAt
                    + "）。如需申诉，可在登录页提交封禁复核申请。");
        }
        // H1-3：先通过封禁检查，再原子复检锁定并清零；若此刻已锁定，不清零也不签发。
        long now = System.currentTimeMillis();
        LoginFailure locked = loginFailures.compute(canonical, (k, s) -> {
            if (s != null && s.lockedUntil > now) return s;
            return null;
        });
        if (locked != null) throw lockedException(locked.lockedUntil, now);
        return rotateSession(((Number) row.get("id")).longValue());
    }

    /** DG-BE-02：用账号行锁串行化同一用户的会话轮换，避免并发登录各自插入一行。 */
    private String rotateSession(long userId) {
        ensureSessionTable();
        String token = UUID.randomUUID().toString();
        String tokenHash = hashSessionToken(token);
        var tx = new TransactionTemplate(new DataSourceTransactionManager(jdbc.getDataSource()));
        tx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
        tx.executeWithoutResult(status -> {
            jdbc.queryForObject("SELECT id FROM app_user WHERE id=? FOR UPDATE", Long.class, userId);
            jdbc.update("DELETE FROM auth_session WHERE user_id=?", userId);
            long now = System.currentTimeMillis();
            jdbc.update("INSERT INTO auth_session (token_hash, user_id, created_at, last_access_at) VALUES (?, ?, ?, ?)",
                    tokenHash, userId, now, now);
        });
        return token;
    }

    /** 锁定期间抛 IllegalStateException，文案带剩余分钟；锁定已过期则不拦截并等待计数重置。 */
    private void requireNotLocked(String account) {
        LoginFailure state = loginFailures.get(account);
        if (state == null) return;
        long now = System.currentTimeMillis();
        if (state.lockedUntil > now) throw lockedException(state.lockedUntil, now);
    }

    private void recordLoginFailure(String account) {
        long now = System.currentTimeMillis();
        loginFailures.compute(account, (k, state) -> {
            // 锁定已过期时从零重新计数；仍在锁定窗口内则不重复累加。
            if (state == null || (state.lockedUntil > 0 && state.lockedUntil <= now))
                state = new LoginFailure(0, 0);
            if (state.lockedUntil > now) return state;
            int count = state.count + 1;
            long lockedUntil = count >= MAX_LOGIN_FAILURES ? now + LOGIN_LOCK_MILLIS : 0;
            return new LoginFailure(count, lockedUntil);
        });
    }

    private static IllegalStateException lockedException(long lockedUntil, long now) {
        long remainingMinutes = Math.max(1, (lockedUntil - now + 59_999) / 60_000);
        return new IllegalStateException("登录失败次数过多，账号已锁定，剩余 "
                + remainingMinutes + " 分钟");
    }

    public Long userId(String authHeader) {
        if (authHeader == null || !authHeader.startsWith("Bearer ")) return null;
        String token = authHeader.substring(7);
        if (token.isBlank()) return null;
        String tokenHash = hashSessionToken(token);
        ensureSessionTable();
        while (true) {
            var rows = jdbc.queryForList(
                    "SELECT user_id, created_at, last_access_at FROM auth_session WHERE token_hash=?", tokenHash);
            if (rows.isEmpty()) return null;
            var row = rows.get(0);
            long now = System.currentTimeMillis();
            long createdAt = ((Number) row.get("created_at")).longValue();
            long lastAccessAt = ((Number) row.get("last_access_at")).longValue();
            // DG-BE-02：先判绝对到期，再判空闲到期；续期不改变签发时间。
            if (now - createdAt >= SESSION_ABSOLUTE_MILLIS) {
                jdbc.update("DELETE FROM auth_session WHERE token_hash=?", tokenHash);
                return null;
            }
            long idleFor = now - lastAccessAt;
            if (idleFor >= SESSION_IDLE_MILLIS) {
                // DG-BE-02：若并发请求已续期则重新读取，避免按旧访问时间误删。
                if (jdbc.update("DELETE FROM auth_session WHERE token_hash=? AND last_access_at=?",
                        tokenHash, lastAccessAt) != 0) return null;
                continue;
            }
            if (idleFor >= SESSION_TOUCH_MILLIS) {
                jdbc.update("UPDATE auth_session SET last_access_at=? WHERE token_hash=? AND last_access_at<=?",
                        now, tokenHash, now - SESSION_TOUCH_MILLIS);
            }
            return ((Number) row.get("user_id")).longValue();
        }
    }

    /** #8 复核-a：兼容 Bearer 头与裸令牌，只撤销当前令牌；无令牌 / 已失效时保持幂等。 */
    public void logout(String authHeader) {
        if (authHeader == null) return;
        String token = authHeader.trim();
        if (token.startsWith("Bearer ")) token = token.substring(7).trim();
        if (token.isEmpty() || "Bearer".equals(token)) return;
        ensureSessionTable();
        jdbc.update("DELETE FROM auth_session WHERE token_hash=?", hashSessionToken(token));
    }

    public Map<String, Object> me(Long userId) {
        return jdbc.queryForMap(
                "SELECT id, account, nickname, role, status, contact FROM app_user WHERE id = ?", userId);
    }

    /** #2 B2-4：登录响应专用，不带 contact；/me 与 updateProfile 仍用 me()，contact 读写不受影响。 */
    public Map<String, Object> meForLogin(Long userId) {
        var profile = new LinkedHashMap<>(me(userId));
        profile.remove("contact");
        return profile;
    }

    /** 阶段一 A5：资料修改（当前只有昵称）。规则与注册一致：非空、1-30 字（按码点计）。
     *  校验失败抛 ValidationException，由 v1 controller 映射为 400 + fieldErrors.nickname。 */
    public Map<String, Object> updateNickname(long userId, String nickname) {
        if (nickname == null || nickname.isBlank())
            throw new ValidationException("nickname", "昵称需为 1-30 字");
        if (nickname.codePointCount(0, nickname.length()) > 30)
            throw new ValidationException("nickname", "昵称需为 1-30 字");
        jdbc.update("UPDATE app_user SET nickname=? WHERE id=?", nickname, userId);
        return me(userId);
    }

    /** A4 序号2：昵称 + 联系方式。所有字段校验通过后才写库，避免部分更新；
     *  contact 允许空串清空、最多 100 字，未提交的字段保留原值。 */
    public Map<String, Object> updateProfile(long userId, boolean nicknameProvided, String nickname,
                                             boolean contactProvided, String contact) {
        Map<String, String> errors = new LinkedHashMap<>();
        if (!nicknameProvided && !contactProvided)
            errors.put("nickname", "请提供要修改的资料");
        if (nicknameProvided && (nickname == null || nickname.isBlank()
                || nickname.codePointCount(0, nickname.length()) > 30))
            errors.put("nickname", "昵称需为 1-30 字");
        if (contactProvided && contact == null)
            errors.put("contact", "联系方式格式不正确");
        if (contactProvided && contact != null
                && contact.codePointCount(0, contact.length()) > 100)
            errors.put("contact", "联系方式不能超过 100 字");
        if (!errors.isEmpty())
            throw new ValidationException(errors, errors.values().iterator().next());
        if (nicknameProvided && contactProvided)
            jdbc.update("UPDATE app_user SET nickname=?, contact=? WHERE id=?", nickname, contact, userId);
        else if (nicknameProvided)
            jdbc.update("UPDATE app_user SET nickname=? WHERE id=?", nickname, userId);
        else
            jdbc.update("UPDATE app_user SET contact=? WHERE id=?", contact, userId);
        return me(userId);
    }

    /** 任务 10（2026-11-09）：改密码。校验原密码、新密码符合 SDD 规则
     *  （8–64 位、含字母与数字）后更新散列，并撤销该用户全部旧会话 token
     *  （含当前 token，改完须重新登录；参考 SDD“凭据更新、旧会话撤销在同一事务提交”）。
     *  摘要决定 1（2026-11-11）：演示账号豁免 SDD 密码规则——种子演示账号按
     *  REQUIREMENTS.md 已知偏差使用 Dazi@2026!，改回 Dazi@2026! 时不做强度拦截。 */
    public void changePassword(long userId, String oldPassword, String newPassword) {
        if (oldPassword == null || oldPassword.isBlank() || newPassword == null || newPassword.isBlank())
            throw new IllegalStateException("请填写原密码与新密码");
        var rows = jdbc.queryForList("SELECT password_hash, account FROM app_user WHERE id=?", userId);
        if (rows.isEmpty()) throw new IllegalStateException("账号不存在");
        if (!verify(oldPassword, (String) rows.get(0).get("password_hash")))
            throw new IllegalStateException("原密码不正确");
        // 摘要决定 1（2026-11-11）：demo01–demo20 / organizer / temp01–temp03 豁免 SDD 密码规则，
        // 种子演示账号按 REQUIREMENTS.md 已知偏差使用 Dazi@2026!；普通账号仍走原强度校验。
        String account = (String) rows.get(0).get("account");
        boolean demoAccount = account != null
                && account.matches("^(demo(0[1-9]|1[0-9]|20)|organizer|temp0[1-3])$");
        if (!demoAccount && (newPassword.length() < 8 || newPassword.length() > 64
                || newPassword.chars().noneMatch(Character::isLetter)
                || newPassword.chars().noneMatch(Character::isDigit)))
            throw new IllegalStateException("新密码须为 8–64 位，且含字母与数字");
        jdbc.update("UPDATE app_user SET password_hash=? WHERE id=?", hash(newPassword), userId);
        revokeSessionsForUser(userId);
    }

    /** DG-BE-02：撤销某用户的全部持久化会话。 */
    public void revokeSessionsForUser(long userId) {
        ensureSessionTable();
        jdbc.update("DELETE FROM auth_session WHERE user_id=?", userId);
    }

    /** DG-BE-02：演示重置后必须清空，否则序列重启会让旧 token 指向新注册的同 id 用户。
     *  H1-2：同时清登录失败计数与锁定状态，避免重置后残留锁定把种子账号锁死。 */
    public void clearSessions() {
        ensureSessionTable();
        jdbc.update("DELETE FROM auth_session");
        loginFailures.clear();
    }
}
