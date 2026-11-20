package com.campusbuddy.config;

import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

/**
 * 2026-11-17：活动封面图上传目录的静态资源映射。
 * <p>
 * 上传文件落在应用工作目录下的 uploads/（可用 UPLOAD_DIR 覆盖），jar 外持久化；
 * 以 /uploads/** 对外提供访问。相对路径统一按 System.getProperty("user.dir")
 * 解析为绝对路径，避免受 Tomcat 临时工作目录影响。
 */
@Configuration
public class WebConfig implements WebMvcConfigurer {
    private final String uploadDir;

    public WebConfig(@Value("${app.upload-dir:uploads}") String uploadDir) {
        this.uploadDir = uploadDir;
    }

    /** 上传目录绝对路径：相对路径按应用工作目录解析。 */
    private Path uploadPath() {
        Path path = Paths.get(uploadDir);
        if (!path.isAbsolute()) {
            path = Paths.get(System.getProperty("user.dir")).resolve(path);
        }
        return path.normalize().toAbsolutePath();
    }

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        registry.addResourceHandler("/uploads/**")
                .addResourceLocations("file:" + uploadPath() + "/");
    }

    /** 启动时确保上传目录存在，首次上传无需再判断。 */
    @PostConstruct
    public void ensureUploadDir() throws IOException {
        Files.createDirectories(uploadPath());
    }
}
