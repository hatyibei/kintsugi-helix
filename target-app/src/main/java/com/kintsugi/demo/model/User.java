package com.kintsugi.demo.model;

import jakarta.persistence.*;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import java.time.LocalDateTime;

/**
 * User entity with some intentional issues:
 * - Missing null checks
 * - Potential NPE in equals/hashCode
 */
@Entity
@Table(name = "users")
public class User {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @NotBlank
    @Column(nullable = false)
    private String name;

    @Email
    @Column(unique = true)
    private String email;

    private String password; // BUG: Password stored in plain text

    private LocalDateTime createdAt;

    private LocalDateTime lastLogin;

    @Column(name = "is_active")
    private Boolean active; // BUG: Can be null, causing NPE

    public User() {
    }

    public User(String name, String email) {
        this.name = name;
        this.email = email;
        this.createdAt = LocalDateTime.now();
        // BUG: active not initialized, defaults to null
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getEmail() {
        return email;
    }

    public void setEmail(String email) {
        this.email = email;
    }

    public String getPassword() {
        return password;
    }

    public void setPassword(String password) {
        // BUG: No password hashing
        this.password = password;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(LocalDateTime createdAt) {
        this.createdAt = createdAt;
    }

    public LocalDateTime getLastLogin() {
        return lastLogin;
    }

    public void setLastLogin(LocalDateTime lastLogin) {
        this.lastLogin = lastLogin;
    }

    public Boolean getActive() {
        return active;
    }

    public void setActive(Boolean active) {
        this.active = active;
    }

    // BUG: isActive() can throw NPE if active is null
    public boolean isActive() {
        return active; // Auto-unboxing NPE when active is null
    }

    // BUG: Potential NPE in equals
    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;
        User user = (User) o;
        return email.equals(user.email); // NPE if email is null
    }

    // BUG: Potential NPE in hashCode
    @Override
    public int hashCode() {
        return email.hashCode(); // NPE if email is null
    }

    @Override
    public String toString() {
        // BUG: Exposing password in toString
        return "User{id=" + id + ", name='" + name + "', email='" + email +
               "', password='" + password + "'}";
    }
}
