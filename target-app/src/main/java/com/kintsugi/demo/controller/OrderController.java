package com.kintsugi.demo.controller;

import com.kintsugi.demo.model.Order;
import com.kintsugi.demo.service.OrderService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * Order REST controller with validation and state issues.
 */
@RestController
@RequestMapping("/api/orders")
public class OrderController {

    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @PostMapping
    public ResponseEntity<Order> createOrder(@RequestBody Map<String, Long> request) {
        Long userId = request.get("userId");

        // BUG: No null check on userId
        Order order = orderService.createOrder(userId);
        return ResponseEntity.ok(order);
    }

    /**
     * BUG: No validation of price (could be negative)
     * BUG: No validation of quantity (could be zero or negative)
     */
    @PostMapping("/{orderId}/items")
    public ResponseEntity<Order> addItem(
            @PathVariable Long orderId,
            @RequestBody Map<String, Object> request) {

        String productName = (String) request.get("productName");
        BigDecimal price = new BigDecimal(request.get("price").toString());
        int quantity = ((Number) request.get("quantity")).intValue();

        // BUG: Accepts negative prices and quantities
        Order order = orderService.addItemToOrder(orderId, productName, price, quantity);
        return ResponseEntity.ok(order);
    }

    @PostMapping("/{orderId}/discount")
    public ResponseEntity<Order> applyDiscount(
            @PathVariable Long orderId,
            @RequestBody Map<String, String> request) {

        String promoCode = request.get("promoCode");
        Order order = orderService.applyDiscount(orderId, promoCode);
        return ResponseEntity.ok(order);
    }

    @PostMapping("/{orderId}/confirm")
    public ResponseEntity<Order> confirmOrder(@PathVariable Long orderId) {
        Order order = orderService.confirmOrder(orderId);
        return ResponseEntity.ok(order);
    }

    /**
     * BUG: No authorization - anyone can cancel any order
     */
    @PostMapping("/{orderId}/cancel")
    public ResponseEntity<Order> cancelOrder(@PathVariable Long orderId) {
        Order order = orderService.cancelOrder(orderId);
        return ResponseEntity.ok(order);
    }

    @GetMapping("/user/{userId}")
    public ResponseEntity<List<Order>> getOrdersByUser(@PathVariable Long userId) {
        List<Order> orders = orderService.getOrdersByUser(userId);
        return ResponseEntity.ok(orders);
    }

    @GetMapping("/pending")
    public ResponseEntity<List<Order>> getPendingOrders() {
        List<Order> orders = orderService.getPendingOrders();
        return ResponseEntity.ok(orders);
    }

    /**
     * BUG: Exposes internal business metric without authorization
     */
    @GetMapping("/revenue")
    public ResponseEntity<Map<String, Object>> getTotalRevenue() {
        double revenue = orderService.calculateTotalRevenue();
        return ResponseEntity.ok(Map.of("totalRevenue", revenue));
    }
}
