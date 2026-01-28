package com.kintsugi.demo.controller;

import com.kintsugi.demo.model.User;
import com.kintsugi.demo.service.UserService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * User REST controller with security and validation issues.
 */
@RestController
@RequestMapping("/api/users")
public class UserController {

    private static final Logger log = LoggerFactory.getLogger(UserController.class);

    private final UserService userService;

    public UserController(UserService userService) {
        this.userService = userService;
    }

    /**
     * BUG: No input validation
     * BUG: Returns password in response
     */
    @PostMapping
    public ResponseEntity<User> createUser(@RequestBody Map<String, String> request) {
        String name = request.get("name");
        String email = request.get("email");
        String password = request.get("password");

        // BUG: No validation
        User user = userService.createUser(name, email, password);

        // BUG: Returns full user including password
        return ResponseEntity.ok(user);
    }

    @GetMapping("/{id}")
    public ResponseEntity<User> getUser(@PathVariable Long id) {
        return userService.findById(id)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    /**
     * BUG: No pagination
     * BUG: Exposes all users including passwords
     */
    @GetMapping
    public ResponseEntity<List<User>> getAllUsers() {
        List<User> users = userService.getAllUsers();
        return ResponseEntity.ok(users);
    }

    /**
     * BUG: SQL Injection vulnerable through search parameter
     */
    @GetMapping("/search")
    public ResponseEntity<List<User>> searchUsers(@RequestParam String name) {
        log.info("Searching for users with name: {}", name);
        List<User> users = userService.searchUsers(name);
        return ResponseEntity.ok(users);
    }

    /**
     * BUG: Authentication endpoint returns too much info
     * BUG: Timing attack vulnerable
     */
    @PostMapping("/authenticate")
    public ResponseEntity<Map<String, Object>> authenticate(@RequestBody Map<String, String> request) {
        String email = request.get("email");
        String password = request.get("password");

        boolean authenticated = userService.authenticate(email, password);

        if (authenticated) {
            User user = userService.findByEmail(email).orElse(null);
            // BUG: Returns full user object including password
            return ResponseEntity.ok(Map.of(
                    "success", true,
                    "user", user,
                    "message", "Authentication successful"
            ));
        } else {
            // BUG: Reveals whether email exists
            if (userService.findByEmail(email).isPresent()) {
                return ResponseEntity.status(401).body(Map.of(
                        "success", false,
                        "message", "Invalid password for email: " + email
                ));
            } else {
                return ResponseEntity.status(401).body(Map.of(
                        "success", false,
                        "message", "No user found with email: " + email
                ));
            }
        }
    }

    @PutMapping("/{id}")
    public ResponseEntity<User> updateUser(
            @PathVariable Long id,
            @RequestBody Map<String, String> request) {

        String name = request.get("name");
        String email = request.get("email");

        try {
            User user = userService.updateUser(id, name, email);
            return ResponseEntity.ok(user);
        } catch (RuntimeException e) {
            // BUG: Exposes internal error message
            return ResponseEntity.badRequest().build();
        }
    }

    /**
     * BUG: No authorization check - anyone can delete any user
     */
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> deleteUser(@PathVariable Long id) {
        userService.deleteUser(id);
        return ResponseEntity.noContent().build();
    }

    @PostMapping("/{id}/deactivate")
    public ResponseEntity<User> deactivateUser(@PathVariable Long id) {
        try {
            User user = userService.deactivateUser(id);
            return ResponseEntity.ok(user);
        } catch (RuntimeException e) {
            return ResponseEntity.notFound().build();
        }
    }
}
