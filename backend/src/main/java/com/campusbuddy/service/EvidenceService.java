package com.campusbuddy.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.sql.PreparedStatement;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

/**
 * DG-BE-07（SDD §6.12 / §7）：治理证据文件。
 * <p>
 * 上传只落盘 + 写暂存行（complaint_id / appeal_id / recovery_request_id 三外键全 NULL），
 * 暂存件任何人不可下载；案件提交时由 GovernanceService 在同事务内校验并绑定其一外键，
 * 绑定后仅申请人（owner）本人或任一启用管理员可下载。证据目录是受控目录，
 * 绝不注册静态资源映射（区别于封面图用的 WebConfig /uploads/**），只能经
 * EvidenceController 每次校验权限后以二进制流下发。
 */
@Service
public class EvidenceService {
    /** 单件上限 5MB（SDD §7），与封面图上传口径一致。 */
    private static final long MAX_SIZE = 5L * 1024 * 1024;

    private static final byte[] PNG_MAGIC =
            {(byte) 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A};
    private static final byte[] JPEG_MAGIC = {(byte) 0xFF, (byte) 0xD8, (byte) 0xFF};
    private static final byte[] PDF_MAGIC = {0x25, 0x50, 0x44, 0x46, 0x2D}; // "%PDF-"

    private final JdbcTemplate jdbc;
    private final String evidenceDir;

    public EvidenceService(JdbcTemplate jdbc,
                           @Value("${app.evidence-dir:${EVIDENCE_DIR:evidence}}") String evidenceDir) {
        this.jdbc = jdbc;
        this.evidenceDir = evidenceDir;
    }

    /** 证据目录绝对路径：相对路径按应用工作目录解析（照 WebConfig.uploadPath 写法）。 */
    private Path evidencePath() {
        Path path = Paths.get(evidenceDir);
        if (!path.isAbsolute()) {
            path = Paths.get(System.getProperty("user.dir")).resolve(path);
        }
        return path.normalize().toAbsolutePath();
    }

    /** 下载载体：文件字节 + 落库的原始文件名与 MIME（storage_key 永不外泄）。 */
    public record EvidenceFile(byte[] bytes, String originalName, String mimeType) {
    }

    /** 嗅探结果：规范 MIME 与规范扩展名。 */
    private record Sniffed(String mimeType, String extension) {
    }

    private static boolean startsWith(byte[] bytes, byte[] magic) {
        if (bytes.length < magic.length) return false;
        for (int i = 0; i < magic.length; i++) {
            if (bytes[i] != magic[i]) return false;
        }
        return true;
    }

    private static Sniffed sniff(byte[] bytes) {
        if (startsWith(bytes, PNG_MAGIC)) return new Sniffed("image/png", ".png");
        if (startsWith(bytes, JPEG_MAGIC)) return new Sniffed("image/jpeg", ".jpg");
        if (startsWith(bytes, PDF_MAGIC)) return new Sniffed("application/pdf", ".pdf");
        return null;
    }

    private static String extensionOf(String filename) {
        if (filename == null) return null;
        int dot = filename.lastIndexOf('.');
        if (dot < 0 || dot == filename.length() - 1) return null;
        return filename.substring(dot).toLowerCase(Locale.ROOT);
    }

    /** original_name 落库前清理：剥路径、去 CR/LF、截断 255；为空返回 null 由调用方兜底。 */
    private static String cleanOriginalName(String filename) {
        if (filename == null) return null;
        String name = filename;
        int cut = Math.max(name.lastIndexOf('/'), name.lastIndexOf('\\'));
        if (cut >= 0) name = name.substring(cut + 1);
        name = name.replace("\r", "").replace("\n", "").trim();
        if (name.length() > 255) name = name.substring(0, 255);
        return name.isEmpty() ? null : name;
    }

    /**
     * 上传暂存：三重校验（魔数 + 声明 MIME + 扩展名）仅 PNG/JPEG/PDF、单件 ≤5MB；
     * 落盘名 = UUID storage_key，写暂存行（三外键 NULL），返回文件编号与元数据。
     */
    public Map<String, Object> store(long ownerId, String originalFilename,
                                     String declaredContentType, byte[] bytes) {
        if (bytes == null || bytes.length == 0)
            throw new ValidationException("file", "请选择要上传的文件");
        if (bytes.length > MAX_SIZE)
            throw new ValidationException("file", "文件不能超过 5MB");
        Sniffed sniffed = sniff(bytes);
        if (sniffed == null)
            throw new ValidationException("file", "仅支持 PNG、JPEG、PDF 文件");
        String declared = declaredContentType == null ? ""
                : declaredContentType.split(";", 2)[0].trim().toLowerCase(Locale.ROOT);
        if (!sniffed.mimeType().equals(declared))
            throw new ValidationException("file", "仅支持 PNG、JPEG、PDF 文件");
        String ext = extensionOf(originalFilename);
        boolean extOk = switch (sniffed.extension()) {
            case ".png" -> ".png".equals(ext);
            case ".jpg" -> ".jpg".equals(ext) || ".jpeg".equals(ext);
            case ".pdf" -> ".pdf".equals(ext);
            default -> false;
        };
        if (!extOk)
            throw new ValidationException("file", "仅支持 PNG、JPEG、PDF 文件");

        byte[] sha256;
        try {
            sha256 = MessageDigest.getInstance("SHA-256").digest(bytes);
        } catch (Exception e) {
            throw new IllegalStateException("SHA-256 不可用", e);
        }
        String storageKey = UUID.randomUUID() + sniffed.extension();
        String originalName = cleanOriginalName(originalFilename);
        if (originalName == null) originalName = storageKey;

        Path dir = evidencePath();
        Path target = dir.resolve(storageKey);
        try {
            Files.createDirectories(dir);
            Files.write(target, bytes);
        } catch (IOException e) {
            throw new IllegalStateException("证据文件保存失败，请重试", e);
        }
        long id;
        try {
            KeyHolder keyHolder = new GeneratedKeyHolder();
            String cleanName = originalName;
            jdbc.update(con -> {
                PreparedStatement ps = con.prepareStatement(
                        "INSERT INTO evidence_file(owner_id, storage_key, original_name, " +
                                "mime_type, size_bytes, sha256) VALUES (?,?,?,?,?,?)",
                        new String[]{"id"});
                ps.setLong(1, ownerId);
                ps.setString(2, storageKey);
                ps.setString(3, cleanName);
                ps.setString(4, sniffed.mimeType());
                ps.setLong(5, bytes.length);
                ps.setBytes(6, sha256);
                return ps;
            }, keyHolder);
            id = keyHolder.getKey().longValue();
        } catch (RuntimeException e) {
            // 落库失败不留孤儿文件。
            try {
                Files.deleteIfExists(target);
            } catch (IOException ignored) {
                // 尽力删除，原始异常照常抛出。
            }
            throw e;
        }
        var rows = jdbc.queryForList("SELECT created_at FROM evidence_file WHERE id=?", id);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", id);
        out.put("original_name", originalName);
        out.put("mime_type", sniffed.mimeType());
        out.put("size_bytes", (long) bytes.length);
        out.put("created_at", rows.isEmpty() ? null : iso(rows.get(0).get("created_at")));
        return out;
    }

    /**
     * 下载读取：暂存件一律 Forbidden；已绑定件仅 owner 本人或任一启用管理员可读。
     * 管理员判定在本类以 SQL 实现（与 GovernanceService.isAdmin 同口径），不反向依赖治理服务。
     */
    public EvidenceFile loadForDownload(long evidenceId, long requesterId) {
        var rows = jdbc.queryForList("SELECT * FROM evidence_file WHERE id=?", evidenceId);
        if (rows.isEmpty()) throw new IllegalStateException("证据文件不存在");
        var row = rows.get(0);
        if (row.get("complaint_id") == null && row.get("appeal_id") == null
                && row.get("recovery_request_id") == null)
            throw new ForbiddenException("证据尚未关联案件，不可下载");
        long ownerId = ((Number) row.get("owner_id")).longValue();
        if (requesterId != ownerId && !isEnabledAdmin(requesterId))
            throw new ForbiddenException("无权下载该证据文件");
        String storageKey = (String) row.get("storage_key");
        Path dir = evidencePath();
        Path target = dir.resolve(storageKey).normalize();
        if (!target.startsWith(dir))
            throw new IllegalStateException("证据文件实体缺失");
        byte[] bytes;
        try {
            bytes = Files.readAllBytes(target);
        } catch (IOException e) {
            throw new IllegalStateException("证据文件实体缺失", e);
        }
        return new EvidenceFile(bytes, (String) row.get("original_name"),
                (String) row.get("mime_type"));
    }

    private boolean isEnabledAdmin(long userId) {
        Integer n = jdbc.queryForObject(
                "SELECT COUNT(*) FROM administrator WHERE user_id=? AND enabled=1",
                Integer.class, userId);
        return n != null && n > 0;
    }

    /** MySQL 驱动返回 LocalDateTime、PostgreSQL 驱动返回 Timestamp，统一归一化（照 GovernanceService 口径）。 */
    private static LocalDateTime asLocalDateTime(Object v) {
        if (v instanceof LocalDateTime ldt) return ldt;
        if (v instanceof Timestamp t) return t.toLocalDateTime();
        if (v instanceof java.util.Date d) return new Timestamp(d.getTime()).toLocalDateTime();
        throw new IllegalStateException("无法识别的时间类型: " + v);
    }

    private static String iso(Object v) {
        return v == null ? null : asLocalDateTime(v).toString();
    }
}
