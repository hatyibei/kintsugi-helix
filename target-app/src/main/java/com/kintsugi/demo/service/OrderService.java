package com.kintsugi.demo.service;

import com.kintsugi.demo.model.Order;
import com.kintsugi.demo.model.Order.OrderStatus;
import com.kintsugi.demo.model.OrderItem;
import com.kintsugi.demo.model.User;
import com.kintsugi.demo.repository.OrderRepository;
import com.kintsugi.demo.repository.UserRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.List;

/**
 * Order service with calculation and state management bugs.
 */
@Service
@Transactional
public class OrderService {

    private static final Logger log = LoggerFactory.getLogger(OrderService.class);

    private final OrderRepository orderRepository;
    private final UserRepository userRepository;

    public OrderService(OrderRepository orderRepository, UserRepository userRepository) {
        this.orderRepository = orderRepository;
        this.userRepository = userRepository;
    }

    public Order createOrder(Long userId) {
        log.info("Creating order for user: {}", userId);

        User user = userRepository.findById(userId)
                .orElseThrow(() -> new RuntimeException("User not found"));

        // BUG: Doesn't check if user is active
        Order order = new Order();
        order.setUser(user);
        order.setDiscount(BigDecimal.ZERO);

        return orderRepository.save(order);
    }

    public Order addItemToOrder(Long orderId, String productName, BigDecimal price, int quantity) {
        Order order = orderRepository.findById(orderId)
                .orElseThrow(() -> new RuntimeException("Order not found"));

        // BUG: Doesn't validate order status before modification
        OrderItem item = new OrderItem(productName, price, quantity);
        order.addItem(item);

        return orderRepository.save(order);
    }

    /**
     * BUG: Doesn't handle concurrent modifications
     */
    public Order applyDiscount(Long orderId, String promoCode) {
        Order order = orderRepository.findById(orderId)
                .orElseThrow(() -> new RuntimeException("Order not found"));

        order.applyPromoCode(promoCode);

        return orderRepository.save(order);
    }

    public Order confirmOrder(Long orderId) {
        Order order = orderRepository.findById(orderId)
                .orElseThrow(() -> new RuntimeException("Order not found"));

        // BUG: Doesn't validate current status
        order.setStatus(OrderStatus.CONFIRMED);

        log.info("Order {} confirmed, total: {}", orderId, order.getTotalAmount());

        return orderRepository.save(order);
    }

    /**
     * BUG: Invalid state transition allowed
     */
    public Order cancelOrder(Long orderId) {
        Order order = orderRepository.findById(orderId)
                .orElseThrow(() -> new RuntimeException("Order not found"));

        // BUG: Can cancel even delivered orders
        order.setStatus(OrderStatus.CANCELLED);

        return orderRepository.save(order);
    }

    public List<Order> getOrdersByUser(Long userId) {
        return orderRepository.findByUserId(userId);
    }

    public List<Order> getPendingOrders() {
        return orderRepository.findByStatus(OrderStatus.PENDING);
    }

    /**
     * BUG: Calculates revenue incorrectly
     * - Uses double arithmetic
     * - Doesn't handle cancelled orders
     */
    public double calculateTotalRevenue() {
        List<Order> allOrders = orderRepository.findAll();

        double total = 0.0; // BUG: Using double for money

        for (Order order : allOrders) {
            // BUG: Includes cancelled orders
            if (order.getTotalAmount() != null) {
                total += order.getTotalAmount().doubleValue();
            }
        }

        return total;
    }

    /**
     * BUG: Memory leak potential - loads all orders into memory
     */
    public Order findLargestOrder() {
        List<Order> allOrders = orderRepository.findAll();

        Order largest = null;
        BigDecimal maxAmount = BigDecimal.ZERO;

        for (Order order : allOrders) {
            // BUG: NPE if totalAmount is null
            if (order.getTotalAmount().compareTo(maxAmount) > 0) {
                maxAmount = order.getTotalAmount();
                largest = order;
            }
        }

        return largest;
    }
}
