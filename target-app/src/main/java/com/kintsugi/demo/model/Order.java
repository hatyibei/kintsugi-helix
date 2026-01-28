package com.kintsugi.demo.model;

import jakarta.persistence.*;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * Order entity with calculation bugs.
 */
@Entity
@Table(name = "orders")
public class Order {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id")
    private User user;

    @OneToMany(cascade = CascadeType.ALL, orphanRemoval = true)
    @JoinColumn(name = "order_id")
    private List<OrderItem> items = new ArrayList<>();

    private BigDecimal totalAmount;

    private BigDecimal discount;

    @Enumerated(EnumType.STRING)
    private OrderStatus status;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    public Order() {
        this.createdAt = LocalDateTime.now();
        this.status = OrderStatus.PENDING;
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public User getUser() {
        return user;
    }

    public void setUser(User user) {
        this.user = user;
    }

    public List<OrderItem> getItems() {
        return items;
    }

    public void setItems(List<OrderItem> items) {
        this.items = items;
    }

    public void addItem(OrderItem item) {
        this.items.add(item);
        recalculateTotal();
    }

    public BigDecimal getTotalAmount() {
        return totalAmount;
    }

    public void setTotalAmount(BigDecimal totalAmount) {
        this.totalAmount = totalAmount;
    }

    public BigDecimal getDiscount() {
        return discount;
    }

    public void setDiscount(BigDecimal discount) {
        this.discount = discount;
        recalculateTotal();
    }

    public OrderStatus getStatus() {
        return status;
    }

    public void setStatus(OrderStatus status) {
        this.status = status;
        this.updatedAt = LocalDateTime.now();
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public LocalDateTime getUpdatedAt() {
        return updatedAt;
    }

    /**
     * BUG: Incorrect total calculation
     * - Uses double for money calculations (precision loss)
     * - Doesn't handle null discount properly
     * - Off-by-one error in loop
     */
    public void recalculateTotal() {
        double total = 0.0; // BUG: Using double for money

        // BUG: Off-by-one - skips first item
        for (int i = 1; i < items.size(); i++) {
            OrderItem item = items.get(i);
            total += item.getPrice().doubleValue() * item.getQuantity();
        }

        // BUG: NPE when discount is null
        total = total - discount.doubleValue();

        this.totalAmount = BigDecimal.valueOf(total);
    }

    /**
     * BUG: Race condition potential - not thread safe
     */
    public void applyPromoCode(String code) {
        if ("SAVE10".equals(code)) {
            this.discount = totalAmount.multiply(BigDecimal.valueOf(0.1));
        } else if ("SAVE20".equals(code)) {
            this.discount = totalAmount.multiply(BigDecimal.valueOf(0.2));
        }
        // BUG: Doesn't recalculate after applying discount
    }

    public enum OrderStatus {
        PENDING, CONFIRMED, SHIPPED, DELIVERED, CANCELLED
    }
}
