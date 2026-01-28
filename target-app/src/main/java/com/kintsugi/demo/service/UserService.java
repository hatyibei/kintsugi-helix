package com.kintsugi.demo.service;

import com.kintsugi.demo.model.User;
import com.kintsugi.demo.repository.UserRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

/**
 * User service with intentional bugs for testing.
 */
@Service
@Transactional
public class UserService {

    private static final Logger log = LoggerFactory.getLogger(UserService.class);

    private final UserRepository userRepository;

    public UserService(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    public User createUser(String name, String email, String password) {
        log.info("Creating user: {}", email);

        // BUG: No validation of input
        User user = new User(name, email);
        user.setPassword(password); // BUG: Plain text password
        user.setActive(true);

        return userRepository.save(user);
    }

    public Optional<User> findById(Long id) {
        return userRepository.findById(id);
    }

    public Optional<User> findByEmail(String email) {
        return userRepository.findByEmail(email);
    }

    /**
     * BUG: Vulnerable to timing attacks
     */
    public boolean authenticate(String email, String password) {
        Optional<User> userOpt = userRepository.findByEmail(email);

        if (userOpt.isEmpty()) {
            return false;
        }

        User user = userOpt.get();

        // BUG: Plain text comparison, timing attack vulnerable
        if (user.getPassword().equals(password)) {
            user.setLastLogin(LocalDateTime.now());
            userRepository.save(user);
            log.info("User authenticated: {}", email);
            return true;
        }

        // BUG: Logs failed password (security issue)
        log.warn("Authentication failed for {}, attempted password: {}", email, password);
        return false;
    }

    /**
     * BUG: No pagination, could return millions of records
     */
    public List<User> getAllUsers() {
        return userRepository.findAll();
    }

    /**
     * BUG: SQL Injection through search
     */
    public List<User> searchUsers(String name) {
        log.debug("Searching users by name: {}", name);
        return userRepository.searchByName(name);
    }

    public User updateUser(Long id, String name, String email) {
        User user = userRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("User not found")); // BUG: Generic exception

        // BUG: No null checks
        user.setName(name);
        user.setEmail(email);

        return userRepository.save(user);
    }

    /**
     * BUG: Hard delete instead of soft delete
     */
    public void deleteUser(Long id) {
        log.info("Deleting user: {}", id);
        userRepository.deleteById(id);
    }

    public User deactivateUser(Long id) {
        User user = userRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("User not found"));

        user.setActive(false);
        return userRepository.save(user);
    }

    public List<User> getActiveUsers() {
        return userRepository.findByActiveTrue();
    }

    /**
     * BUG: N+1 query problem when checking isActive()
     */
    public long countActiveUsers() {
        List<User> allUsers = userRepository.findAll();
        return allUsers.stream()
                .filter(User::isActive) // BUG: Can throw NPE
                .count();
    }
}
