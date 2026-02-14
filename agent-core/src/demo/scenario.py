"""Demo scenario data for Kintsugi-Helix demonstration.

Provides realistic pre-configured bug scenarios with actual source code
from the target-app for live demonstration of the full repair pipeline.
"""

# ============================================================================
# Simulated Cloud Logging Error Entries
# ============================================================================

DEMO_ERROR_LOGS = [
    {
        "timestamp": "2026-02-15T10:23:45.123Z",
        "severity": "ERROR",
        "service": "kintsugi-demo-app",
        "revision": "demo-app-00012-abc",
        "message": "java.lang.NullPointerException: Cannot invoke \"com.kintsugi.demo.model.User.getEmail()\" because \"user\" is null",
        "trace": """java.lang.NullPointerException: Cannot invoke "com.kintsugi.demo.model.User.getEmail()" because "user" is null
\tat com.kintsugi.demo.service.OrderService.createOrder(OrderService.java:42)
\tat com.kintsugi.demo.controller.OrderController.createOrder(OrderController.java:28)
\tat java.base/jdk.internal.reflect.NativeMethodAccessorImpl.invoke(NativeMethodAccessorImpl.java:77)
\tat org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:885)
\tat org.apache.catalina.core.ApplicationFilterChain.internalDoFilter(ApplicationFilterChain.java:178)""",
        "http_request": {
            "method": "POST",
            "url": "/api/orders",
            "status": 500,
            "latency": "0.045s",
        },
        "trace_id": "a1b2c3d4e5f6",
        "count": 47,
    },
]

# ============================================================================
# Target Source Code (from actual target-app files)
# ============================================================================

BUGGY_ORDER_SERVICE = '''package com.kintsugi.demo.service;

import com.kintsugi.demo.model.Order;
import com.kintsugi.demo.model.OrderItem;
import com.kintsugi.demo.model.User;
import com.kintsugi.demo.repository.OrderRepository;
import com.kintsugi.demo.repository.UserRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@Service
public class OrderService {

    private final OrderRepository orderRepository;
    private final UserRepository userRepository;

    public OrderService(OrderRepository orderRepository, UserRepository userRepository) {
        this.orderRepository = orderRepository;
        this.userRepository = userRepository;
    }

    @Transactional
    public Order createOrder(Long userId, List<OrderItem> items) {
        // BUG: findById returns Optional, but .get() without isPresent check
        // causes NullPointerException when user doesn't exist
        User user = userRepository.findById(userId).orElse(null);

        // This line throws NPE when user is null
        String email = user.getEmail();

        Order order = new Order();
        order.setUser(user);
        order.setEmail(email);
        order.setItems(items);
        order.setCreatedAt(LocalDateTime.now());
        order.setTotalAmount(calculateTotal(items));
        order.setStatus("PENDING");

        return orderRepository.save(order);
    }

    public Optional<Order> getOrder(Long orderId) {
        return orderRepository.findById(orderId);
    }

    public List<Order> getUserOrders(Long userId) {
        return orderRepository.findByUserId(userId);
    }

    private BigDecimal calculateTotal(List<OrderItem> items) {
        return items.stream()
                .map(item -> item.getPrice().multiply(BigDecimal.valueOf(item.getQuantity())))
                .reduce(BigDecimal.ZERO, BigDecimal::add);
    }
}'''

FIXED_ORDER_SERVICE = '''package com.kintsugi.demo.service;

import com.kintsugi.demo.model.Order;
import com.kintsugi.demo.model.OrderItem;
import com.kintsugi.demo.model.User;
import com.kintsugi.demo.repository.OrderRepository;
import com.kintsugi.demo.repository.UserRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@Service
public class OrderService {

    private final OrderRepository orderRepository;
    private final UserRepository userRepository;

    public OrderService(OrderRepository orderRepository, UserRepository userRepository) {
        this.orderRepository = orderRepository;
        this.userRepository = userRepository;
    }

    @Transactional
    public Order createOrder(Long userId, List<OrderItem> items) {
        // FIXED: Properly handle Optional with orElseThrow
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new IllegalArgumentException(
                        "User not found with ID: " + userId));

        String email = user.getEmail();

        Order order = new Order();
        order.setUser(user);
        order.setEmail(email);
        order.setItems(items);
        order.setCreatedAt(LocalDateTime.now());
        order.setTotalAmount(calculateTotal(items));
        order.setStatus("PENDING");

        return orderRepository.save(order);
    }

    public Optional<Order> getOrder(Long orderId) {
        return orderRepository.findById(orderId);
    }

    public List<Order> getUserOrders(Long userId) {
        return orderRepository.findByUserId(userId);
    }

    private BigDecimal calculateTotal(List<OrderItem> items) {
        return items.stream()
                .map(item -> item.getPrice().multiply(BigDecimal.valueOf(item.getQuantity())))
                .reduce(BigDecimal.ZERO, BigDecimal::add);
    }
}'''

# ============================================================================
# Generated Test Code
# ============================================================================

GENERATED_TEST_CODE = '''package com.kintsugi.demo.service;

import com.kintsugi.demo.model.Order;
import com.kintsugi.demo.model.OrderItem;
import com.kintsugi.demo.model.User;
import com.kintsugi.demo.repository.OrderRepository;
import com.kintsugi.demo.repository.UserRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("OrderService Bug Reproduction - NPE on missing user")
class OrderServiceBugReproductionTest {

    @Mock
    private OrderRepository orderRepository;

    @Mock
    private UserRepository userRepository;

    @InjectMocks
    private OrderService orderService;

    private List<OrderItem> sampleItems;

    @BeforeEach
    void setUp() {
        OrderItem item = new OrderItem();
        item.setPrice(BigDecimal.valueOf(29.99));
        item.setQuantity(2);
        sampleItems = List.of(item);
    }

    @Test
    @DisplayName("Should throw NPE when user ID does not exist - BUG REPRODUCTION")
    void createOrder_withNonExistentUser_shouldThrowNPE() {
        // Given: User does not exist in database
        when(userRepository.findById(999L)).thenReturn(Optional.empty());

        // When & Then: NPE is thrown (this is the bug)
        assertThrows(NullPointerException.class, () -> {
            orderService.createOrder(999L, sampleItems);
        });
    }

    @Test
    @DisplayName("Should succeed when user exists")
    void createOrder_withExistingUser_shouldSucceed() {
        // Given: User exists
        User user = new User();
        user.setId(1L);
        user.setEmail("test@example.com");
        when(userRepository.findById(1L)).thenReturn(Optional.of(user));
        when(orderRepository.save(any(Order.class))).thenAnswer(i -> i.getArgument(0));

        // When
        Order order = orderService.createOrder(1L, sampleItems);

        // Then
        assertNotNull(order);
        assertEquals("test@example.com", order.getEmail());
        assertEquals("PENDING", order.getStatus());
    }
}'''

# ============================================================================
# Code Diff
# ============================================================================

CODE_DIFF = '''--- a/src/main/java/com/kintsugi/demo/service/OrderService.java
+++ b/src/main/java/com/kintsugi/demo/service/OrderService.java
@@ -30,8 +30,9 @@
     @Transactional
     public Order createOrder(Long userId, List<OrderItem> items) {
-        // BUG: findById returns Optional, but .get() without isPresent check
-        // causes NullPointerException when user doesn't exist
-        User user = userRepository.findById(userId).orElse(null);
-
-        // This line throws NPE when user is null
-        String email = user.getEmail();
+        // FIXED: Properly handle Optional with orElseThrow
+        User user = userRepository.findById(userId)
+                .orElseThrow(() -> new IllegalArgumentException(
+                        "User not found with ID: " + userId));
+
+        String email = user.getEmail();'''

# ============================================================================
# RCA Result (fallback if Gemini call fails)
# ============================================================================

FALLBACK_RCA = {
    "summary": "NullPointerException in OrderService.createOrder() due to missing null check on user lookup",
    "root_cause": "The method userRepository.findById(userId) returns Optional.empty() when user doesn't exist, but .orElse(null) converts it to null. The subsequent call to user.getEmail() on line 42 dereferences null, causing NullPointerException.",
    "affected_component": "com.kintsugi.demo.service.OrderService",
    "suggested_fix": "Replace orElse(null) with orElseThrow(() -> new IllegalArgumentException(\"User not found\")) to properly handle the missing user case with a descriptive exception.",
    "confidence": 0.95,
    "related_files": [
        "src/main/java/com/kintsugi/demo/service/OrderService.java",
        "src/main/java/com/kintsugi/demo/repository/UserRepository.java",
        "src/main/java/com/kintsugi/demo/controller/OrderController.java",
    ],
    "severity": "high",
    "fix_type": "null_safety",
}

FALLBACK_BLAST_RADIUS = {
    "score": 0.25,
    "risk_level": "low",
    "files_affected": 2,
    "dependencies_affected": ["OrderController", "UserRepository"],
    "recommendation": "auto_merge",
    "reasoning": "The fix changes error handling from silent null to explicit exception. It affects a single service method with 2 direct dependents. The fix is additive (adding validation) rather than modifying business logic, making it safe for auto-merge. No data model changes are involved.",
    "business_impact": {
        "affected_features": ["Order creation"],
        "affected_endpoints": ["POST /api/orders"],
        "user_facing_impact": "Users will receive a clear '400 Bad Request' error instead of '500 Internal Server Error' when ordering with invalid user ID",
        "data_integrity_risk": "none",
    },
}

LEARNING_ENTRY = {
    "bug_type": "NullPointerException",
    "pattern": "Optional.orElse(null) followed by method invocation",
    "fix_pattern": "Replace with Optional.orElseThrow() with descriptive message",
    "confidence": 0.95,
    "key_insight": "Spring Data JPA findById() returns Optional - always use orElseThrow() or ifPresent() instead of orElse(null) to prevent NPE cascades",
    "similar_risks": [
        "UserService.findById() has the same pattern",
        "Any repository method returning Optional",
    ],
}
