package com.kintsugi.demo.service;

import com.kintsugi.demo.model.User;
import com.kintsugi.demo.repository.UserRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Arrays;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class UserServiceTest {

    @Mock
    private UserRepository userRepository;

    @InjectMocks
    private UserService userService;

    private User testUser;

    @BeforeEach
    void setUp() {
        testUser = new User("Test User", "test@example.com");
        testUser.setId(1L);
        testUser.setPassword("password123");
        testUser.setActive(true);
    }

    @Test
    @DisplayName("Should create user successfully")
    void createUser_Success() {
        when(userRepository.save(any(User.class))).thenReturn(testUser);

        User created = userService.createUser("Test User", "test@example.com", "password123");

        assertNotNull(created);
        assertEquals("Test User", created.getName());
        verify(userRepository).save(any(User.class));
    }

    @Test
    @DisplayName("Should authenticate user with correct password")
    void authenticate_Success() {
        when(userRepository.findByEmail("test@example.com")).thenReturn(Optional.of(testUser));
        when(userRepository.save(any(User.class))).thenReturn(testUser);

        boolean result = userService.authenticate("test@example.com", "password123");

        assertTrue(result);
    }

    @Test
    @DisplayName("Should reject authentication with wrong password")
    void authenticate_WrongPassword() {
        when(userRepository.findByEmail("test@example.com")).thenReturn(Optional.of(testUser));

        boolean result = userService.authenticate("test@example.com", "wrongpassword");

        assertFalse(result);
    }

    @Test
    @DisplayName("Should find user by ID")
    void findById_Success() {
        when(userRepository.findById(1L)).thenReturn(Optional.of(testUser));

        Optional<User> found = userService.findById(1L);

        assertTrue(found.isPresent());
        assertEquals("Test User", found.get().getName());
    }

    /**
     * This test demonstrates the NPE bug in countActiveUsers()
     * when a user has null active field.
     */
    @Test
    @DisplayName("Should count active users - FAILS due to NPE bug")
    void countActiveUsers_NullActiveBug() {
        User userWithNullActive = new User("Null User", "null@example.com");
        // active field is null by default - this will cause NPE

        when(userRepository.findAll()).thenReturn(Arrays.asList(testUser, userWithNullActive));

        // This will throw NPE due to the bug in User.isActive()
        assertThrows(NullPointerException.class, () -> {
            userService.countActiveUsers();
        });
    }
}
